"""
engine/llm_reasoner.py

Pipeline boxes 6.2 (Hypothesis Generation) + 6.3 (Investigation Planning) —
the REASONER: the "brain" that decides what the loop does each step.

HOW THIS FITS
-------------
bounded_loop.py never calls an LLM itself. It calls a pluggable reasoner with
ONE method:

        reasoner.next_action(context) -> AgentAction

Until now that was FakeReasoner (replays a fixed script, no LLM). This file is
the REAL reasoner with the SAME one method. The loop cannot tell them apart, so
nothing in bounded_loop.py / case_memory.py / the tools has to change.

WHAT IT DOES EACH STEP
----------------------
1. Receives `context` (the loop's _build_context): the case-memory summary,
   the tool list, and the last observation.
2. Wraps it in a prompt: the investigator's job + the tool contract (arg
   names/types) + the exact JSON reply it must produce + the forensic rules.
3. Calls the local model on the VM (Ollama, via langchain-ollama's ChatOllama —
   the same convention as the lab's lang-graph-basic starter).
4. Parses the model's reply into ONE JSON object and TRANSLATES it into an
   AgentAction — the same dataclass FakeReasoner returns.

MODEL CONNECTION (matches lang-graph-basic)
-------------------------------------------
Reads the same environment variables as the lab's starter, so the whole group
points at the model server the same way:
    OLLAMA_MODEL        (e.g. qwen2.5:7b-instruct while building; qwen2.5-coder:32b for real runs)
    OLLAMA_BASE_URL     (default http://localhost:11434)
    OLLAMA_TEMPERATURE  (default 0 — deterministic, which we want for forensics)

NOVELTY GUARDRAILS (W1 / W6) LIVE IN THE PROMPT
-----------------------------------------------
The system prompt tells the model: stay neutral, NEVER assume or name a specific
app, a finding MUST cite an evidence id it actually sees, and "missing != deleted"
(an expected-but-absent artifact is an absence to RECORD, not proof of wiping).
The deterministic stages (correlation 6.6, ach 6.7, self_verification 6.8) then
ENFORCE this regardless of what the model says — the prompt asks, the code checks.
"""

from __future__ import annotations
import json
import os
from typing import Any

from engine.bounded_loop import Reasoner, AgentAction, ActionKind
from engine.tool_catalog import ToolCatalog


# --- model connection (same convention as the lab's lang-graph-basic) --------

def _build_llm(model: str | None = None,
               base_url: str | None = None,
               temperature: float | None = None):
    """
    Create a ChatOllama client. langchain_ollama is imported HERE (not at module
    top) so this file can be imported and unit-tested with no LLM installed —
    tests inject a fake client instead.
    """
    from langchain_ollama import ChatOllama  # local import on purpose
    model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    if temperature is None:
        temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
    return ChatOllama(model=model, base_url=base_url, temperature=temperature)


# --- robust JSON extraction --------------------------------------------------

def extract_first_json_object(text: str) -> dict | None:
    """
    Pull the FIRST balanced {...} object out of a text blob and parse it.

    Small models sometimes wrap JSON in prose or ```json fences; this scans for a
    brace-balanced object (ignoring braces inside strings) and parses it. Returns
    None if nothing parseable is found, so the caller can trigger a repair retry.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict):
                                return obj
                        except json.JSONDecodeError:
                            pass  # not valid; fall through and try the next '{'
                        break
        start = text.find("{", start + 1)
    return None


# --- rendering the tool contract into the prompt -----------------------------

def _render_tool_contract(catalog: ToolCatalog) -> str:
    """
    Turn the catalog's ToolSchemas into a precise, readable block the model can
    follow — name, purpose, and each argument's name/type/required/allowed-set.
    Without this the model would guess argument names and the gate would reject
    every call. (This is the fix for describe_for_prompt() only listing
    name+purpose: we render the full arg list here, in the reasoner, so the
    tested tool_catalog.py stays untouched.)
    """
    lines: list[str] = []
    for tool in catalog.all_tools():
        arg_bits: list[str] = []
        for a in tool.args:
            flag = "required" if a.required else "optional"
            extra = f", one of {a.allowed_values}" if a.allowed_values is not None else ""
            arg_bits.append(f'"{a.name}" ({a.field_type.value}, {flag}{extra}) — {a.description}')
        args_text = "; ".join(arg_bits) if arg_bits else "no arguments"
        lines.append(f"- {tool.name}: {tool.purpose}\n    args: {args_text}")
    return "\n".join(lines)


# --- the system prompt -------------------------------------------------------

_RULES = """\
You are a neutral digital-forensics investigator examining ALREADY-ACQUIRED
Android artifacts from one device. You work ONE step at a time.

Your job each step: look at the case memory and the last observation, then
choose the single next action that best advances the investigation.

HARD RULES (follow exactly):
- Respond with ONE JSON object and NOTHING else. No prose, no markdown fences.
- Choose exactly ONE action per step: "call_tool" (gather evidence),
  "analyze" (connect the dots on evidence you already have), or "conclude".
- You may ONLY call a tool listed in TOOLS below, with its listed arguments.
- After gathering some evidence, use an "analyze" step to CORRELATE: list the
  facts you found as "observations", giving each a short shared "claim_key" (so
  the same fact seen in two sources lines up) and the evidence id it came from.
  List any artifact you EXPECTED under "expected" plus the locators actually
  present under "present_locators"; anything expected-but-missing is recorded as
  an absence to investigate — NOT proof of deletion.
- NEVER assume, guess, or name a specific application. Reason only from what the
  tools actually return. The identity of any tool is an OUTPUT, never an input.
- A "finding" is something a tool PROVED. It MUST cite at least one evidence id
  (like E0001) that you can actually see in the case memory or last observation.
  NEVER invent an evidence id. If you have no evidence id yet, do not claim a
  finding — call a tool first.
- "missing is NOT the same as deleted." If something you expected is absent, do
  not conclude it was wiped. Record it as an "absence" and keep investigating;
  other steps will weigh innocent explanations.
- When the evidence is thin or absent, it is CORRECT to conclude "inconclusive".
  Do not overclaim.

REPLY SCHEMA (include only the keys you need):
{
  "thought": "one or two sentences of your reasoning this step",
  "action": "call_tool" | "analyze" | "conclude",

  // when action == "call_tool":
  "tool_name": "<one of the TOOLS names>",
  "tool_args": { ...arguments for that tool... },
  "keep_fields": ["optional", "list of output fields to keep in full"],

  // when action == "analyze" (correlation, box 6.6):
  "observations": [ {"source_id": "E0001", "claim_key": "wiped_file", "value": "report.pdf"} ],
  "expected": [ {"label": "usage_stats for the app", "locator": "<path>", "reason": "why expected"} ],
  "present_locators": ["<path actually present>", "<another>"],

  // optional bookkeeping you may attach on ANY step:
  "propose_hypothesis": "a theory to track (unproven)",
  "finding": { "statement": "what was proven", "evidence_ids": ["E0001"] },
  "absence": { "looked_for": "...", "location": "...", "suspicious": true,
               "note": "..." },

  // when action == "conclude":
  "conclusion": "your overall conclusion, incl. 'inconclusive' if the evidence is thin"
}
"""


class LLMReasoner(Reasoner):
    """
    The real reasoner. Same interface as FakeReasoner — one next_action(context).

    Construction:
        catalog      : the ToolCatalog (so the prompt can list real tool args)
        model/base_url/temperature : optional overrides; otherwise env vars
        llm          : an optional pre-built client (tests inject a fake here;
                       in production leave it None and it builds ChatOllama lazily)
        max_repairs  : how many times to re-ask when the reply isn't valid JSON
    """

    def __init__(self, catalog: ToolCatalog, *,
                 model: str | None = None,
                 base_url: str | None = None,
                 temperature: float | None = None,
                 llm: Any = None,
                 max_repairs: int = 1) -> None:
        self.catalog = catalog
        self._model = model
        self._base_url = base_url
        self._temperature = temperature
        self._llm = llm                      # None until first use (or injected)
        self.max_repairs = max_repairs
        self._tool_contract = _render_tool_contract(catalog)
        self.last_raw_reply = ""             # kept for debugging / token accounting

    # -- the model client (built lazily so import/tests need no LLM) ----------

    @property
    def llm(self):
        if self._llm is None:
            self._llm = _build_llm(self._model, self._base_url, self._temperature)
        return self._llm

    def _ask(self, prompt: str) -> str:
        """Send one prompt, return the reply text."""
        reply = self.llm.invoke(prompt)
        content = getattr(reply, "content", reply)
        return content if isinstance(content, str) else str(content)

    # -- the prompt -----------------------------------------------------------

    def _system_prompt(self) -> str:
        return f"{_RULES}\n\nTOOLS (the only tools you may call):\n{self._tool_contract}"

    # -- the one method the loop calls ----------------------------------------

    def next_action(self, context: str) -> AgentAction:
        prompt = (
            self._system_prompt()
            + "\n\n=== CURRENT CASE STATE ===\n" + context
            + "\n\nReturn ONE JSON object now:"
        )

        text = self._ask(prompt)
        self.last_raw_reply = text
        doc = extract_first_json_object(text)

        tries = 0
        while doc is None and tries < self.max_repairs:
            tries += 1
            repair = (
                prompt
                + "\n\nYour previous reply was NOT a single valid JSON object:\n"
                + text[:1000]
                + "\n\nReturn ONLY one JSON object — no prose, no markdown fences."
            )
            text = self._ask(repair)
            self.last_raw_reply = text
            doc = extract_first_json_object(text)

        if doc is None:
            # Honest, bounded failure: stop rather than loop or crash.
            # (Future improvement: feed the parse error back as an observation
            #  and let the loop re-plan — noted in the deferred list.)
            return AgentAction(
                thought="planner produced no valid JSON after repair",
                kind=ActionKind.CONCLUDE,
                conclusion="planner_error: could not obtain a valid JSON action",
            )

        return self._action_from_doc(doc)

    # -- translate the model's JSON into an AgentAction -----------------------

    def _action_from_doc(self, doc: dict) -> AgentAction:
        thought = str(doc.get("thought", "")).strip()
        action = str(doc.get("action", "")).strip().lower()

        # shared optional bookkeeping (the model may attach these on any step)
        propose = str(doc.get("propose_hypothesis", "") or "").strip()

        finding_statement = ""
        finding_evidence_ids: list[str] = []
        finding = doc.get("finding")
        if isinstance(finding, dict):
            finding_statement = str(finding.get("statement", "") or "").strip()
            ids = finding.get("evidence_ids", [])
            if isinstance(ids, list):
                finding_evidence_ids = [str(x) for x in ids]

        absence = None
        raw_absence = doc.get("absence")
        if isinstance(raw_absence, dict) and raw_absence.get("looked_for"):
            # keep ONLY the keys record_absence() accepts
            absence = {
                "looked_for": str(raw_absence.get("looked_for", "")),
                "location": str(raw_absence.get("location", "")),
                "suspicious": bool(raw_absence.get("suspicious", False)),
                "note": str(raw_absence.get("note", "")),
            }

        # correlation inputs (box 6.6): sanitize each dict to only the keys we use
        observations = None
        raw_obs = doc.get("observations")
        if isinstance(raw_obs, list):
            observations = [
                {"source_id": str(o.get("source_id", "")),
                 "claim_key": str(o.get("claim_key", "")),
                 "value": str(o.get("value", ""))}
                for o in raw_obs if isinstance(o, dict)
            ]

        expected = None
        raw_exp = doc.get("expected")
        if isinstance(raw_exp, list):
            expected = [
                {"label": str(e.get("label", "")),
                 "locator": str(e.get("locator", "")),
                 "reason": str(e.get("reason", ""))}
                for e in raw_exp if isinstance(e, dict)
            ]

        present_locators = None
        raw_pres = doc.get("present_locators")
        if isinstance(raw_pres, list):
            present_locators = [str(x) for x in raw_pres]

        # map the action word to a kind: analyze / conclude / (default) call_tool
        if action == "conclude":
            return AgentAction(
                thought=thought,
                kind=ActionKind.CONCLUDE,
                conclusion=str(doc.get("conclusion", "") or "").strip(),
                propose=propose,
                finding_statement=finding_statement,
                finding_evidence_ids=finding_evidence_ids,
                absence=absence,
                observations=observations,
                expected=expected,
                present_locators=present_locators,
            )

        if action == "analyze":
            return AgentAction(
                thought=thought,
                kind=ActionKind.ANALYZE,
                propose=propose,
                finding_statement=finding_statement,
                finding_evidence_ids=finding_evidence_ids,
                absence=absence,
                observations=observations,
                expected=expected,
                present_locators=present_locators,
            )

        # Default to CALL_TOOL. If the model gave a bad/missing action or an
        # unknown tool, we still return CALL_TOOL — the validation gate will
        # reject it and the loop re-plans (bounded by the step budget).
        tool_name = str(doc.get("tool_name", "") or "").strip()
        tool_args = doc.get("tool_args", {})
        if not isinstance(tool_args, dict):
            tool_args = {}

        keep_fields = doc.get("keep_fields")
        if isinstance(keep_fields, list):
            keep_fields = [str(x) for x in keep_fields]
        else:
            keep_fields = None

        return AgentAction(
            thought=thought,
            kind=ActionKind.CALL_TOOL,
            tool_name=tool_name,
            tool_args=tool_args,
            keep_fields=keep_fields,
            propose=propose,
            finding_statement=finding_statement,
            finding_evidence_ids=finding_evidence_ids,
            absence=absence,
            observations=observations,
            expected=expected,
            present_locators=present_locators,
        )