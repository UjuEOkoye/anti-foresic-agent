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
import json
import time
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
    conclusion: str = ""                           # the model's own explanation (prose)
    verdict: str = ""                              # "detected" | "not_detected" | "inconclusive"
    category: str = ""                             # e.g. "artifact_wiping" (required for "detected")
    conclusion_evidence_ids: list[str] = field(default_factory=list)  # evidence the verdict rests on


@dataclass
class InvestigationResult:
    """What the loop returns when it stops."""
    status: str            # "concluded" | "inconclusive"
    reason: str
    memory: CaseMemory     # the full case notebook (hypotheses, findings, absences, log)
    audit: Any             # the AuditStore holding every full-raw result
    steps_used: int
    # STRUCTURED VERDICT (Fix 3, 2026-11-17). Set by CODE, not by the model's prose:
    verdict: str = "inconclusive"        # detected | not_detected | inconclusive
    category: str = ""                   # PROVISIONAL SoK category when detected (box 7 finalises)
    confidence: str = "n/a"              # from the ACH gate (6.7): high | reduced | n/a
    evidence_ids: list = field(default_factory=list)
    ach_claim: str = ""                  # the claim whose ACH result set the confidence
    explanation: str = ""                # the model's own words (never sets the verdict)


@dataclass
class GateState:
    """
    The EFFECTIVE result of the alternative-hypothesis check (6.7) that the
    conclusion gate uses. Normally a copy of the latest ACH result; but if a
    re-check tried to RAISE confidence without any new evidence, it keeps the
    earlier (lower) result instead (Fix A).
    """
    claim: str
    clears: bool
    confidence: str          # "blocked" | "reduced" | "high"
    summary: str

    def verdict(self) -> str:
        return self.summary


_CONFIDENCE_RANK = {"blocked": 0, "reduced": 1, "high": 2}


# Verdicts and categories the conclusion may use (SoK categories in scope).
VERDICTS = ("detected", "not_detected", "inconclusive")
DETECTION_CATEGORIES = {
    "artifact_wiping": "artifact_wiping", "aw": "artifact_wiping",
    "trail_obfuscation": "trail_obfuscation", "to": "trail_obfuscation",
    "data_hiding": "data_hiding", "dh": "data_hiding",
    "presence_installation": "presence_installation", "pia": "presence_installation",
    # Pipeline box 7 allows "other-supported / Unknown-Unclassified": an anti-forensic
    # behaviour the evidence supports but that fits no known category. Needed for
    # RQ3 (behaviours not in the knowledge base) — never force a known label.
    "unclassified": "unclassified", "unknown": "unclassified", "other": "unclassified",
}


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
                 dual: DualOutput | None = None, knowledge_base: Any = None,
                 progress: bool = False) -> None:
        self.reasoner = reasoner
        self.catalog = catalog
        self.max_steps = max_steps
        self.memory = memory or CaseMemory()
        self.dual = dual or DualOutput()
        self.kb = knowledge_base          # box 6.2 textbook (optional; None = no KB)
        self.progress = progress          # print one live line per step (so a slow run is visibly alive)
        self._last_ach: Any = None        # effective ACH (6.7) gate state -> sets the verdict's confidence
        self._ach_evidence_seen: int = -1 # distinct evidence count when that check ran (Fix A)
        # PINNED CONTEXT (fixes "agent amnesia"): before this, the agent only saw the
        # LAST observation, so the artifact list vanished after step 1 and each tool
        # result vanished after the next step. Now both stay visible every step.
        self._briefing: str = ""                       # task + artifact inventory
        self._evidence_views: list[tuple[str, str]] = []   # (header, compact view)
        self._read_paths: set[str] = set()             # artifact paths already read

    # Each pinned evidence view is capped so the prompt cannot grow without limit.
    # (The FULL raw result is always in the audit store; this is only the agent's view.)
    MAX_VIEW_CHARS = 2500

    def _distinct_evidence(self) -> int:
        """
        How many DISTINCT pieces of evidence have been gathered, counted by content
        hash. Re-reading the same file gives the same hash, so it is not 'new'
        evidence; a new file or a new search result is.
        """
        return len({rec["hash"] for rec in getattr(self.dual.audit, "_records", {}).values()})

    def _evidence_exists(self, evidence_id: str) -> bool:
        try:
            self.dual.audit.get(evidence_id)
            return True
        except KeyError:
            return False

    def _inventory_paths(self) -> list[str]:
        """Artifact paths listed in the briefing (lines that start with '/')."""
        return [ln.strip() for ln in self._briefing.splitlines() if ln.strip().startswith("/")]

    def _pinned_block(self) -> str:
        """Briefing + every piece of evidence gathered so far + what is still unread."""
        if not self._briefing and not self._evidence_views:
            return ""
        parts: list[str] = []
        if self._briefing:
            parts.append("=== CASE BRIEFING (always available) ===\n" + self._briefing)
        parts.append(f"=== EVIDENCE GATHERED SO FAR ({len(self._evidence_views)}) ===")
        if self._evidence_views:
            for header, view in self._evidence_views:
                parts.append(header + "\n" + view)
        else:
            parts.append("(none yet)")
        unread = [p for p in self._inventory_paths() if p not in self._read_paths]
        if self._briefing:
            parts.append("=== ARTIFACTS NOT YET READ (%d) ===" % len(unread))
            parts.append("\n".join(unread) if unread else
                         "(all listed artifacts have been read — analyze and conclude)")
        return "\n".join(parts)

    def _build_context(self, last_observation: Any) -> str:
        """What the reasoner sees each step (becomes the LLM prompt later)."""
        pinned = self._pinned_block()
        context = (
            self.memory.summary_for_prompt()
            + ("\n\n" + pinned if pinned else "")
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

    def run(self, initial_observation: str | None = None) -> InvestigationResult:
        # main.py seeds this with the capture's artifact inventory (real paths) so
        # the agent does not have to invent paths. Default keeps old behaviour.
        last_observation: Any = initial_observation or "Investigation started. No evidence gathered yet."
        self._briefing = initial_observation or ""     # pin it for EVERY step

        while self.memory.step < self.max_steps:
            step = self.memory.advance_step()

            # REASON (6.2 + 6.3)
            context = self._build_context(last_observation)
            t0 = time.time()
            if self.progress:
                print(f"[step {step}/{self.max_steps}] thinking... "
                      f"(prompt ~{len(context) // 4} tokens)", flush=True)
            action = self.reasoner.next_action(context)
            if self.progress:
                what = action.kind.value + (f" {action.tool_name}" if action.tool_name else "")
                print(f"[step {step}/{self.max_steps}] -> {what}  ({time.time() - t0:.0f}s)",
                      flush=True)
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
                    rationale = str(a.get("rationale", ""))
                    # FIX A (2026-11-17), rule 1: ruling out an alternative needs EVIDENCE.
                    # "ruled_out" citing no existing evidence id counts as "cannot_exclude".
                    if disp == Disposition.RULED_OUT and not any(self._evidence_exists(e) for e in ev):
                        self.memory.log("ach_detail", f"  {cat.value}: 'ruled_out' cites no existing "
                                                      f"evidence {ev} -> treated as cannot_exclude")
                        disp = Disposition.CANNOT_EXCLUDE
                    # Audit trail (RQ5): every judgment, its reason and its evidence.
                    self.memory.log("ach_detail", f"  {cat.value}: {disp.value} "
                                                  f"[{', '.join(ev) or 'no evidence'}] — {rationale}")
                    assessments.append(AltAssessment(category=cat, disposition=disp,
                                                     rationale=rationale, evidence_ids=ev))
                ach = run_ach_stage(self.memory, str(action.alt_check.get("claim", "")), assessments)
                gate = GateState(ach.claim, ach.clears, ach.confidence, ach.verdict())
                # FIX A, rule 2: a re-check may LOWER confidence at any time, but may only
                # RAISE it if new evidence was gathered since the previous check. Run #4
                # went BLOCKED -> HIGH in one step with no tool call: only the opinion changed.
                seen_now = self._distinct_evidence()
                prev = self._last_ach
                if (prev is not None and seen_now == self._ach_evidence_seen
                        and _CONFIDENCE_RANK[gate.confidence] > _CONFIDENCE_RANK[prev.confidence]):
                    self.memory.log("ach", f"ACH CAPPED: confidence cannot rise from "
                                           f"{prev.confidence.upper()} to {gate.confidence.upper()} "
                                           f"without new evidence since the previous check -> stays "
                                           f"{prev.confidence.upper()}")
                    gate = GateState(ach.claim, prev.clears, prev.confidence,
                                     f"{prev.summary} [re-check without new evidence: capped]")
                self._last_ach = gate     # the BINDING gate for a "detected" verdict (Fix 3)
                self._ach_evidence_seen = seen_now
                note = f"ACH (6.7): {gate.confidence.upper()} — {gate.verdict()}"
                if "capped" in gate.summary:
                    note += (" To raise confidence, gather NEW evidence (e.g. an artifact or "
                             "search not yet done) that addresses the remaining alternative.")
                analysis_note = (analysis_note + " " + note).strip() if analysis_note else note

            # THINK: ANALYZE -> a pure reasoning step. The bookkeeping above
            # (hypotheses/findings/absences/correlation) already ran; just loop on.
            if action.kind == ActionKind.ANALYZE:
                last_observation = analysis_note or (
                    "Analysis step recorded (no new evidence). Your gathered evidence is "
                    "listed above. If any artifacts are NOT YET READ, read one next.")
                continue

            # terminal: CONCLUDE -> (a) structured verdict + BINDING ACH gate, then (b) 6.8
            if action.kind == ActionKind.CONCLUDE:
                # (a) FIX 3 (2026-11-17). Live run #3: every ACH on the main claim was
                # BLOCKED, yet the model wrote "high confidence ... no plausible
                # alternatives remain". The model's prose must never set the verdict or
                # its confidence. The model STATES a verdict; this code decides whether
                # it may stand, and the confidence comes from the ACH gate alone.
                verdict = (action.verdict or "").strip().lower()
                if verdict not in VERDICTS:
                    self.memory.log("note", f"No valid verdict given ({action.verdict!r}) "
                                            f"-> recorded as 'inconclusive' (conservative default).")
                    verdict = "inconclusive"
                category = DETECTION_CATEGORIES.get((action.category or "").strip().lower(), "")
                ev_ids = [str(e) for e in (action.conclusion_evidence_ids or [])]
                confidence, ach_claim = "n/a", ""

                if verdict == "detected":
                    problems: list[str] = []
                    ach = self._last_ach
                    if ach is None:
                        problems.append("no alt_check has been run on the main claim")
                    elif not ach.clears:
                        problems.append(f"the latest alt_check ('{ach.claim}') is {ach.verdict()}")
                    if not category:
                        problems.append(f"category {action.category!r} is not one of "
                                        f"artifact_wiping / trail_obfuscation / data_hiding / "
                                        f"presence_installation / unclassified")
                    if not ev_ids:
                        problems.append("no evidence_ids were given for the verdict")
                    unknown = [e for e in ev_ids if not self._evidence_exists(e)]
                    if unknown:
                        problems.append(f"evidence ids not in the audit store: {unknown}")
                    if problems:
                        msg = "; ".join(problems)
                        self.memory.log("note", f"CONCLUSION REFUSED by ACH gate (6.7): {msg}")
                        last_observation = (
                            "CONCLUSION REFUSED (box 6.7 gate). A 'detected' verdict needs a "
                            "CLEARING alt_check on the main claim, a valid category and real "
                            f"evidence ids. Problem(s): {msg}. Either run a new alt_check on the "
                            "main claim that addresses each alternative with evidence, or "
                            "conclude with verdict 'inconclusive'.")
                        continue
                    confidence, ach_claim = ach.confidence, ach.claim

                # (b) BOX 6.8 self-verification GATE
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

                # The headline is BUILT BY CODE from the gated fields; the model's prose
                # is kept separately as its explanation.
                if verdict == "detected":
                    reason = (f"VERDICT: DETECTED — {category} | confidence: {confidence.upper()} "
                              f"(set by ACH 6.7 on: '{ach_claim}') | evidence: {', '.join(ev_ids)}")
                else:
                    reason = f"VERDICT: {verdict.upper()}" + (
                        f" | evidence: {', '.join(ev_ids)}" if ev_ids else "")
                self.memory.log("note", f"CONCLUDE: {reason}")
                self.memory.log("note", f"EXPLANATION (model): {action.conclusion}")
                return InvestigationResult("concluded", reason, self.memory, self.dual.audit, step,
                                           verdict=verdict, category=category if verdict == "detected" else "",
                                           confidence=confidence, evidence_ids=ev_ids,
                                           ach_claim=ach_claim, explanation=action.conclusion)

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
                # v1: IGNORE the agent's guessed keep_fields. The agent is not told each
                # tool's OUTPUT field names, so its guesses match nothing and the view
                # comes back empty ("the file is empty"). Pass None -> the full view
                # (long values are still length-truncated). Agent-driven keep_fields
                # returns once we feed the agent each tool's output schema (deferred).
                bundle = self.dual.handle(action.tool_name, raw, keep_fields=None)
                ev_id = bundle["evidence"]["evidence_id"]
                self.memory.log("tool_call", f"{action.tool_name}({action.tool_args}) -> {ev_id}")
                # OBSERVE: feed back the compact view as readable JSON, tagged with its id
                view = json.dumps(bundle["projected"], default=str)
                if len(view) > self.MAX_VIEW_CHARS:
                    view = view[:self.MAX_VIEW_CHARS] + " ...[view truncated; full raw in audit store]"
                path = str(action.tool_args.get("artifact_path", ""))
                self._evidence_views.append((f"[{ev_id}] {action.tool_name} on {path}", view))
                if path:
                    self._read_paths.add(path)
                last_observation = f"[{ev_id}] " + view
                continue

        # budget exhausted -> honest inconclusive (never guess)
        self.memory.log("note",
                        f"Step budget ({self.max_steps}) exhausted — result INCONCLUSIVE.")
        return InvestigationResult("inconclusive",
                                   f"step budget of {self.max_steps} exhausted",
                                   self.memory, self.dual.audit, self.memory.step)