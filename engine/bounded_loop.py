"""
engine/bounded_loop.py

Pipeline BOX 6 — the Bounded AI Investigation (the ReAct loop).

This is the engine that drives all the parts we built (6.1 case memory, 6.4 the
schema validation gate, 6.5 dual output + tools) around a cycle:

    REASON  -> ask the reasoner for the next action   (boxes 6.2 + 6.3)
    ACT     -> validate it (6.4), run the tool, dual-output it (6.5)
    OBSERVE -> write to case memory (6.1), feed the result back
    ... repeat until the agent CONCLUDES or the step budget runs out.

THE KEY DESIGN DECISION: the loop does NOT call an LLM directly. It calls a
pluggable `reasoner` with one method, `next_action(context) -> AgentAction`.
  - Today we plug in a scripted FakeReasoner, so the whole loop can be tested
    with NO LLM, NO GPU, NO cost.
  - Later we plug in an LLMReasoner with the same method; nothing else changes.

"Bounded" = the step budget. The loop can never run forever; when the budget is
spent it reports an honest "inconclusive" instead of guessing (forensically the
correct behavior).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.case_memory import CaseMemory, CaseMemoryError
from engine.tool_catalog import ToolCatalog
from engine.validation_gate import validate_call
from engine.dual_output import DualOutput
from engine.self_verification import run_self_verification   # BOX 6.8
from engine.correlation import run_correlation, Observation, ExpectedArtifact   # BOX 6.6
from engine.ach import run_ach_stage, AltAssessment, AltCategory, Disposition   # BOX 6.7


# --- what the agent can decide to do on a given step -------------------------

class ActionKind(str, Enum):
    CALL_TOOL = "call_tool"   # GATHER: pull evidence with an allow-listed tool
    ANALYZE = "analyze"       # THINK: connect the dots on evidence already gathered (6.6/6.7)
    CONCLUDE = "conclude"     # FINISH: the agent is done; leave the loop


@dataclass
class AgentAction:
    """
    One move the reasoner makes in a step. `thought` + `kind` are always set;
    the rest are optional extras the reasoner may attach.
    """
    thought: str                                   # the agent's reasoning this step (6.2/6.3)
    kind: ActionKind

    # for kind == CALL_TOOL:
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    keep_fields: list[str] | None = None           # passed to dual output's projection

    # optional bookkeeping the reasoner can attach any step:
    propose: str = ""                              # a hypothesis to add (6.2)
    finding_statement: str = ""                    # a grounded finding to accept (6.5)
    finding_evidence_ids: list[str] = field(default_factory=list)
    absence: dict | None = None                    # {looked_for, location, suspicious, note} (6.6/W1)

    # for CORRELATION (box 6.6): facts the agent extracted + what it expected.
    observations: list[dict] | None = None         # each {source_id, claim_key, value}
    expected: list[dict] | None = None             # each {label, locator, reason}
    present_locators: list[str] | None = None      # locators actually present in the capture

    # for ACH (box 6.7 / W6): the claim + the agent's verdict on each innocent story.
    alt_check: dict | None = None                  # {claim, assessments:[{category,disposition,rationale,evidence_ids}]}

    # for kind == CONCLUDE:
    conclusion: str = ""


@dataclass
class InvestigationResult:
    """What the loop returns when it stops."""
    status: str            # "concluded" | "inconclusive"
    reason: str
    memory: CaseMemory     # the full case notebook (hypotheses, findings, absences, log)
    audit: Any             # the AuditStore holding every full-raw result
    steps_used: int


# --- the reasoner seam -------------------------------------------------------

class Reasoner:
    """Interface. A real one wraps an LLM; the fake one replays a script."""
    def next_action(self, context: str) -> AgentAction:
        raise NotImplementedError


class FakeReasoner(Reasoner):
    """
    Replays a fixed list of AgentActions in order, ignoring the context. Lets us
    test the loop's control flow deterministically with no LLM. When the script
    is exhausted it concludes, so the loop can never hang.
    """
    def __init__(self, script: list[AgentAction]) -> None:
        self._script = list(script)
        self._i = 0

    def next_action(self, context: str) -> AgentAction:
        if self._i >= len(self._script):
            return AgentAction(thought="script exhausted", kind=ActionKind.CONCLUDE,
                               conclusion="no more scripted actions")
        action = self._script[self._i]
        self._i += 1
        return action


# --- the loop itself ---------------------------------------------------------

class BoundedInvestigationLoop:
    """Box 6. Drives 6.1-6.8 around the ReAct cycle with a step budget."""

    def __init__(self, reasoner: Reasoner, catalog: ToolCatalog,
                 max_steps: int = 12, memory: CaseMemory | None = None,
                 dual: DualOutput | None = None, knowledge_base: Any = None) -> None:
        self.reasoner = reasoner
        self.catalog = catalog
        self.max_steps = max_steps
        self.memory = memory or CaseMemory()
        self.dual = dual or DualOutput()
        self.kb = knowledge_base          # box 6.2 textbook (optional; None = no KB)

    def _build_context(self, last_observation: Any) -> str:
        """What the reasoner sees each step (becomes the LLM prompt later)."""
        context = (
            self.memory.summary_for_prompt()
            + "\n\nAvailable tools:\n" + self.catalog.describe_for_prompt()
            + "\n\nLast observation:\n" + str(last_observation)
        )
        # BOX 6.2 KNOWLEDGE BASE: consult the general textbook. Build a query from
        # the agent's current open hypotheses + the last observation, retrieve the
        # few most relevant cards, and append them — clearly labelled as general
        # background, NOT case evidence. (No KB attached -> this block is skipped.)
        if self.kb is not None:
            query = " ".join(h.statement for h in self.memory.open_hypotheses())
            query = (query + " " + str(last_observation)).strip()
            cards = self.kb.retrieve(query, k=3) if query else []
            if cards:
                context += "\n\n" + self.kb.as_prompt_block(cards)
        return context

    def run(self) -> InvestigationResult:
        last_observation: Any = "Investigation started. No evidence gathered yet."

        while self.memory.step < self.max_steps:
            step = self.memory.advance_step()

            # REASON (6.2 + 6.3)
            context = self._build_context(last_observation)
            action = self.reasoner.next_action(context)
            self.memory.log("note", f"THOUGHT: {action.thought}")

            # optional: add a hypothesis (6.2)
            if action.propose:
                self.memory.propose_hypothesis(action.propose)

            # optional: accept a grounded finding (6.5 propose->verify->ACCEPT)
            if action.finding_statement:
                try:
                    self.memory.record_finding(action.finding_statement,
                                               action.finding_evidence_ids)
                except CaseMemoryError as exc:
                    # ungrounded finding refused -> tell the agent, re-plan
                    last_observation = f"FINDING REJECTED: {exc}"
                    continue

            # optional: record a suspicious absence (6.6 / W1)
            if action.absence:
                self.memory.record_absence(**action.absence)

            # CORRELATION (BOX 6.6): if the agent handed us facts + expectations,
            # connect the dots (corroborations/conflicts) and compute absences
            # ("missing != deleted"). Deterministic; writes results into memory.
            analysis_note = ""
            if action.observations or action.expected:
                obs = [
                    Observation(source_id=str(o.get("source_id", "")),
                                claim_key=str(o.get("claim_key", "")),
                                value=str(o.get("value", "")))
                    for o in (action.observations or [])
                ]
                exp = [
                    ExpectedArtifact(label=str(e.get("label", "")),
                                     locator=str(e.get("locator", "")),
                                     reason=str(e.get("reason", "")))
                    for e in (action.expected or [])
                ]
                present = set(action.present_locators or [])
                cresult = run_correlation(self.memory, obs, exp, present)
                analysis_note = (
                    f"Correlation (6.6): {len(cresult.corroborations)} corroboration(s), "
                    f"{len(cresult.conflicts)} conflict(s), {len(cresult.absences)} absence(s) recorded."
                )

            # ACH (BOX 6.7 / W6): if the agent handed us a claim + its verdicts on
            # the four innocent explanations, run the devil's-advocate gate. It LOGS
            # a confidence (high / reduced / blocked) that flows to the report.
            if action.alt_check and action.alt_check.get("assessments"):
                _CAT = {
                    "normal": AltCategory.NORMAL, "normal_behavior": AltCategory.NORMAL,
                    "another_app": AltCategory.ANOTHER_APP, "another_application": AltCategory.ANOTHER_APP,
                    "system": AltCategory.SYSTEM_BEHAVIOR, "system_behavior": AltCategory.SYSTEM_BEHAVIOR,
                    "acquisition": AltCategory.ACQUISITION_LIMIT, "acquisition_limit": AltCategory.ACQUISITION_LIMIT,
                }
                _DISP = {
                    "ruled_out": Disposition.RULED_OUT,
                    "plausible": Disposition.PLAUSIBLE,
                    "cannot_exclude": Disposition.CANNOT_EXCLUDE, "cannot_tell": Disposition.CANNOT_EXCLUDE,
                }
                assessments = []
                for a in action.alt_check.get("assessments", []):
                    cat = _CAT.get(str(a.get("category", "")).strip().lower())
                    disp = _DISP.get(str(a.get("disposition", "")).strip().lower())
                    if cat is None or disp is None:
                        continue   # skip an unrecognized category/disposition
                    ev = a.get("evidence_ids", [])
                    ev = [str(x) for x in ev] if isinstance(ev, list) else []
                    assessments.append(AltAssessment(category=cat, disposition=disp,
                                                     rationale=str(a.get("rationale", "")),
                                                     evidence_ids=ev))
                ach = run_ach_stage(self.memory, str(action.alt_check.get("claim", "")), assessments)
                note = f"ACH (6.7): {ach.confidence.upper()} — {ach.verdict()}"
                analysis_note = (analysis_note + " " + note).strip() if analysis_note else note

            # THINK: ANALYZE -> a pure reasoning step. The bookkeeping above
            # (hypotheses/findings/absences/correlation) already ran; just loop on.
            if action.kind == ActionKind.ANALYZE:
                last_observation = analysis_note or "Analysis step recorded; continue investigating."
                continue

            # terminal: CONCLUDE -> run the BOX 6.8 self-verification GATE first
            if action.kind == ActionKind.CONCLUDE:
                # 6.8: check every finding cites real evidence + resolve hypotheses.
                verification = run_self_verification(self.memory, self.dual.audit)
                if not verification.verified:
                    # A finding cites evidence that does not exist (hallucination),
                    # or a hypothesis is confirmed without grounded support. We do
                    # NOT allow a clean conclusion: feed the flags back and re-plan.
                    # (Bounded by the step budget -> ends 'inconclusive' if never fixed:
                    #  you can never CONCLUDE on ungrounded evidence. That is the guarantee.)
                    flags_txt = "; ".join(
                        f"{f.kind}[{f.subject_id}]: {f.detail}" for f in verification.flags
                    )
                    self.memory.log("note", f"CONCLUSION BLOCKED by self-verification (6.8): {flags_txt}")
                    last_observation = (
                        "CONCLUSION BLOCKED by self-verification (box 6.8). "
                        "Every finding must cite evidence that exists; fix or drop these "
                        f"before concluding -> {flags_txt}"
                    )
                    continue

                self.memory.log("note", f"CONCLUDE: {action.conclusion}")
                return InvestigationResult("concluded", action.conclusion,
                                           self.memory, self.dual.audit, step)

            # ACT: CALL_TOOL  (6.4 gate -> 6.5 execute + dual output)
            if action.kind == ActionKind.CALL_TOOL:
                check = validate_call(self.catalog, action.tool_name, action.tool_args)
                if not check.valid:
                    # 6.4: invalid -> structured error -> re-plan; tool NEVER runs
                    self.memory.log("tool_call", f"REJECTED {action.tool_name}: {check.errors}")
                    last_observation = f"TOOL CALL REJECTED: {check.as_observation()}"
                    continue

                tool = self.catalog.get(action.tool_name)          # safe: gate passed
                raw = tool.handler(**action.tool_args)             # 6.5 run the tool
                bundle = self.dual.handle(action.tool_name, raw,   # 6.5 full raw + projected
                                          keep_fields=action.keep_fields)
                ev_id = bundle["evidence"]["evidence_id"]
                self.memory.log("tool_call", f"{action.tool_name} -> {ev_id}")
                # OBSERVE: feed back the compact view, tagged with its evidence id
                last_observation = f"[{ev_id}] {bundle['projected']}"
                continue

        # budget exhausted -> honest inconclusive (never guess)
        self.memory.log("note",
                        f"Step budget ({self.max_steps}) exhausted — result INCONCLUSIVE.")
        return InvestigationResult("inconclusive",
                                   f"step budget of {self.max_steps} exhausted",
                                   self.memory, self.dual.audit, self.memory.step)