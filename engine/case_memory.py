"""
engine/case_memory.py

Pipeline box 6.1 — the Case / Evidence Memory that sits beside the
investigation loop. The agent's case notebook for ONE investigation.

WHY THIS FILE EXISTS
--------------------
The bounded loop (bounded_loop.py) reasons one step at a time. Between steps it
needs somewhere to write down what it has examined, what it believes, what it
has actually PROVEN, and what it looked for but could not find. That notebook is
this file. Nothing here calls an LLM; it is a plain, auditable record.

THE ONE RULE THIS FILE PROTECTS: propose -> verify -> accept
------------------------------------------------------------
A thing the LLM *guesses* and a thing a tool *proved* are kept in SEPARATE
places and can never be confused:

    Hypothesis = something the agent THINKS might be true (unproven).
    Finding    = something a tool actually retrieved + corroborated. Every
                 Finding points to one or more evidence_ids in the audit store
                 (E0001, E0002, ...), so it traces back to full raw evidence
                 plus its SHA-256 hash.

Only Findings are allowed into the final report. The LLM may hypothesize
freely; only the data can confirm. record_finding() REJECTS a finding with no
evidence - a finding with no evidence is just a hypothesis.

ABSENCE IS FIRST-CLASS (our crown-jewel novelty, W1)
----------------------------------------------------
"Found nothing" is not the same as "clean device." When the agent looks for an
artifact that SHOULD be there and it is missing, that absence is recorded as a
NegativeIndicator - and the gap itself can be the finding.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class HypothesisStatus(str, Enum):
    """What has happened to a hypothesis as the investigation progressed."""
    OPEN = "open"            # still being tested
    CONFIRMED = "confirmed"  # a Finding now supports it
    REFUTED = "refuted"      # evidence argued against it
    DROPPED = "dropped"      # abandoned (e.g. a better theory replaced it)


class CaseMemoryError(Exception):
    """Raised when the notebook is used in a way that breaks a core rule."""


def _now() -> str:
    """UTC timestamp, ISO format. Every entry is timestamped for RQ5."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Hypothesis:
    """Something the agent THINKS might be true. Unproven by definition."""
    hyp_id: str                 # H0001, H0002, ...
    statement: str              # "A secure-deletion tool ran on this device"
    rationale: str = ""         # why the agent proposed it
    status: HypothesisStatus = HypothesisStatus.OPEN
    status_reason: str = ""     # why it was confirmed / refuted / dropped
    created_step: int = 0
    created_at: str = field(default_factory=_now)


@dataclass
class Finding:
    """Something a tool PROVED. Must be grounded in real evidence."""
    finding_id: str             # F0001, F0002, ...
    statement: str              # "savekey_reports records a 3-pass DoD wipe"
    evidence_ids: list[str]     # audit-store ids (E0001, ...) that back it up
    hypothesis_id: str = ""     # which hypothesis this supports (optional)
    note: str = ""
    created_step: int = 0
    created_at: str = field(default_factory=_now)


@dataclass
class NegativeIndicator:
    """
    Something the agent looked for and did NOT find. First-class, because an
    expected-but-absent artifact can itself be the evidence of anti-forensics.
    """
    neg_id: str                 # N0001, N0002, ...
    looked_for: str             # "shared_prefs for package X"
    location: str               # where it was expected
    suspicious: bool = False    # is this absence itself a red flag?
    note: str = ""
    created_step: int = 0
    created_at: str = field(default_factory=_now)


@dataclass
class LogEntry:
    """One line in the never-erased investigation log."""
    step: int
    kind: str                   # "hypothesis" | "plan" | "tool_call" | "finding" | "absence" | "note"
    text: str
    at: str = field(default_factory=_now)


class CaseMemory:
    """
    The notebook for a single investigation. The loop owns one of these and
    writes to it every step. Pure data - no reasoning, no LLM.
    """

    def __init__(self) -> None:
        self._hypotheses: dict[str, Hypothesis] = {}
        self._findings: dict[str, Finding] = {}
        self._negatives: dict[str, NegativeIndicator] = {}
        self._log: list[LogEntry] = []
        self._step: int = 0
        # independent counters so ids never collide
        self._h_count = 0
        self._f_count = 0
        self._n_count = 0

    # --- step control -----------------------------------------------------

    def advance_step(self) -> int:
        """Called by the loop once per iteration. Returns the new step number."""
        self._step += 1
        return self._step

    @property
    def step(self) -> int:
        return self._step

    # --- the log ----------------------------------------------------------

    def log(self, kind: str, text: str) -> None:
        """Write a timestamped line to the never-erased investigation log."""
        self._log.append(LogEntry(step=self._step, kind=kind, text=text))

    def full_log(self) -> list[LogEntry]:
        return list(self._log)

    # --- hypotheses (propose) --------------------------------------------

    def propose_hypothesis(self, statement: str, rationale: str = "") -> Hypothesis:
        """The LLM may call this freely. Nothing here is proven."""
        self._h_count += 1
        hyp = Hypothesis(
            hyp_id=f"H{self._h_count:04d}",
            statement=statement,
            rationale=rationale,
            created_step=self._step,
        )
        self._hypotheses[hyp.hyp_id] = hyp
        self.log("hypothesis", f"{hyp.hyp_id}: {statement}")
        return hyp

    def _set_status(self, hyp_id: str, status: HypothesisStatus, reason: str) -> Hypothesis:
        if hyp_id not in self._hypotheses:
            raise CaseMemoryError(f"No such hypothesis: {hyp_id}")
        hyp = self._hypotheses[hyp_id]
        hyp.status = status
        hyp.status_reason = reason
        self.log("hypothesis", f"{hyp_id} -> {status.value} ({reason})")
        return hyp

    def confirm_hypothesis(self, hyp_id: str, reason: str = "") -> Hypothesis:
        return self._set_status(hyp_id, HypothesisStatus.CONFIRMED, reason)

    def refute_hypothesis(self, hyp_id: str, reason: str = "") -> Hypothesis:
        return self._set_status(hyp_id, HypothesisStatus.REFUTED, reason)

    def drop_hypothesis(self, hyp_id: str, reason: str = "") -> Hypothesis:
        return self._set_status(hyp_id, HypothesisStatus.DROPPED, reason)

    def open_hypotheses(self) -> list[Hypothesis]:
        return [h for h in self._hypotheses.values() if h.status == HypothesisStatus.OPEN]

    def all_hypotheses(self) -> list[Hypothesis]:
        """Every hypothesis, any status — needed by self-verification (6.8)."""
        return list(self._hypotheses.values())

    # --- findings (verify -> accept) -------------------------------------

    def record_finding(
        self,
        statement: str,
        evidence_ids: list[str],
        hypothesis_id: str = "",
        note: str = "",
    ) -> Finding:
        """
        Accept something as PROVEN. Enforces grounding: a finding MUST cite at
        least one audit-store evidence_id, or it is rejected. A finding with no
        evidence is just a hypothesis.
        """
        if not evidence_ids:
            raise CaseMemoryError(
                "A finding must cite at least one evidence_id. "
                "Ungrounded claims stay hypotheses."
            )
        self._f_count += 1
        finding = Finding(
            finding_id=f"F{self._f_count:04d}",
            statement=statement,
            evidence_ids=list(evidence_ids),
            hypothesis_id=hypothesis_id,
            note=note,
            created_step=self._step,
        )
        self._findings[finding.finding_id] = finding
        self.log("finding", f"{finding.finding_id}: {statement} [{', '.join(evidence_ids)}]")
        return finding

    def findings_list(self) -> list[Finding]:
        return list(self._findings.values())

    # --- negative indicators (absence is first-class) --------------------

    def record_absence(
        self,
        looked_for: str,
        location: str,
        suspicious: bool = False,
        note: str = "",
    ) -> NegativeIndicator:
        """Record that an expected artifact was NOT found. W1 lives here."""
        self._n_count += 1
        neg = NegativeIndicator(
            neg_id=f"N{self._n_count:04d}",
            looked_for=looked_for,
            location=location,
            suspicious=suspicious,
            note=note,
            created_step=self._step,
        )
        self._negatives[neg.neg_id] = neg
        flag = " (SUSPICIOUS)" if suspicious else ""
        self.log("absence", f"{neg.neg_id}: {looked_for} not found at {location}{flag}")
        return neg

    def negative_indicators(self) -> list[NegativeIndicator]:
        return list(self._negatives.values())

    # --- the view the loop feeds back to the LLM each step ---------------

    def summary_for_prompt(self, recent_log: int = 8) -> str:
        """
        A compact text snapshot the loop hands back to the LLM each iteration,
        so it can see where it is without re-reading everything.
        """
        lines: list[str] = [f"=== CASE MEMORY (step {self._step}) ==="]

        open_h = self.open_hypotheses()
        lines.append(f"Open hypotheses ({len(open_h)}):")
        for h in open_h:
            lines.append(f"  {h.hyp_id}: {h.statement}")

        lines.append(f"Confirmed findings ({len(self._findings)}):")
        for f in self._findings.values():
            lines.append(f"  {f.finding_id}: {f.statement} [{', '.join(f.evidence_ids)}]")

        suspicious = [n for n in self._negatives.values() if n.suspicious]
        lines.append(f"Suspicious absences ({len(suspicious)}):")
        for n in suspicious:
            lines.append(f"  {n.neg_id}: {n.looked_for} missing at {n.location}")

        lines.append("Recent log:")
        for entry in self._log[-recent_log:]:
            lines.append(f"  [step {entry.step}] {entry.kind}: {entry.text}")

        return "\n".join(lines)