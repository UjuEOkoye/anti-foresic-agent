"""
engine/ach.py

Pipeline BOX 6.7 — Alternative-Hypothesis Check (ACH).

The devil's-advocate / anti-confirmation-bias step. Before a claim is allowed to
stand as evidence of anti-forensic activity, it must survive an explicit check
against the four standard INNOCENT explanations:

    1. NORMAL           - could this just be normal app behavior?
    2. ANOTHER_APP      - could a different application have caused it?
    3. SYSTEM_BEHAVIOR  - could the OS/system (reboot, housekeeping) explain it?
    4. ACQUISITION_LIMIT- could we simply have failed to capture it?

THE RULE (deterministic gate, enforced here):
  - Every one of the four MUST be addressed (you cannot skip one = completeness).
  - A claim CLEARS only if none of the four is left "plausible".
  - "cannot_exclude" does not block, but it LOWERS confidence and must be disclosed.

This is W6. It guards against the trap every prior paper fell into: confirming a
hypothesis without ever trying to refute it.

MECHANISM / COGNITION SPLIT:
  - The AGENT (LLM, later) JUDGES each alternative (ruled out / plausible /
    cannot-tell) with a rationale and supporting evidence ids.
  - THIS FILE enforces completeness and computes the gate by fixed rules.
    Deterministic = testable (RQ5) + ablatable (RQ4).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class AltCategory(str, Enum):
    NORMAL = "normal_behavior"
    ANOTHER_APP = "another_application"
    SYSTEM_BEHAVIOR = "system_behavior"
    ACQUISITION_LIMIT = "acquisition_limit"


# All four must be addressed for a claim to be considered checked.
REQUIRED_CATEGORIES = [
    AltCategory.NORMAL,
    AltCategory.ANOTHER_APP,
    AltCategory.SYSTEM_BEHAVIOR,
    AltCategory.ACQUISITION_LIMIT,
]


# WHAT EACH ALTERNATIVE ACTUALLY ASKS (Fix 1, 2026-11-17).
# Live run #1 showed the model treating "normal" as a question about MOTIVE ("a
# person might wipe files for ordinary privacy reasons") and so blocking a
# well-evidenced wipe. That is the wrong question: this system detects whether an
# anti-forensic technique was EXECUTED, not why. Intent is for the investigator /
# court. Every alternative is therefore a question about the EVIDENCE: could it
# exist WITHOUT the claimed technique having actually been executed?
# Single source of truth: the reasoner renders these into the prompt.
ALT_CATEGORY_QUESTIONS: dict[AltCategory, str] = {
    AltCategory.NORMAL: (
        "Could ordinary use have produced this exact evidence WITHOUT the technique "
        "being executed? (e.g. the app was only installed or opened and never ran the "
        "operation; the values are defaults, placeholders, or settings never acted on)"
    ),
    AltCategory.ANOTHER_APP: (
        "Could a DIFFERENT app or component have produced these artifacts, so the "
        "attribution is wrong? (e.g. the records belong to another package; check which "
        "process wrote the relevant log lines and which app that process id belongs to)"
    ),
    AltCategory.SYSTEM_BEHAVIOR: (
        "Could the operating system itself have produced this, with no user-initiated "
        "anti-forensic operation? (e.g. routine cache eviction, log rotation, reboot)"
    ),
    AltCategory.ACQUISITION_LIMIT: (
        "Could the acquisition/extraction process explain this? (e.g. something looks "
        "missing only because it was never collected, or a parse/encoding error)"
    ),
}


def describe_alternatives_for_prompt() -> str:
    """The four alternative questions, formatted for the reasoner's prompt."""
    short = {AltCategory.NORMAL: "normal", AltCategory.ANOTHER_APP: "another_app",
             AltCategory.SYSTEM_BEHAVIOR: "system", AltCategory.ACQUISITION_LIMIT: "acquisition"}
    return "\n".join(f'  - "{short[c]}": {ALT_CATEGORY_QUESTIONS[c]}' for c in REQUIRED_CATEGORIES)

class Disposition(str, Enum):
    RULED_OUT = "ruled_out"            # evidence excludes this innocent explanation
    PLAUSIBLE = "plausible"            # a viable innocent story remains -> BLOCKS a guilty call
    CANNOT_EXCLUDE = "cannot_exclude"  # not enough evidence -> caution, lowers confidence


@dataclass
class AltAssessment:
    """The agent's verdict on ONE innocent explanation for a claim."""
    category: AltCategory
    disposition: Disposition
    rationale: str
    evidence_ids: list[str] = field(default_factory=list)  # support (esp. for ruled_out)


@dataclass
class ACHResult:
    """Outcome of running ACH on one claim."""
    claim: str
    assessments: list[AltAssessment]
    missing_categories: list[AltCategory]   # required ones the agent failed to address
    blocking: list[AltCategory]             # categories still 'plausible'
    cautions: list[AltCategory]             # categories 'cannot_exclude'
    clears: bool                            # may the claim stand as anti-forensic?
    confidence: str                         # "high" | "reduced" | "blocked"

    def verdict(self) -> str:
        if not self.clears:
            if self.missing_categories:
                miss = ", ".join(c.value for c in self.missing_categories)
                return f"BLOCKED — alternatives not fully checked (missing: {miss})"
            block = ", ".join(c.value for c in self.blocking)
            return f"BLOCKED — a viable innocent explanation remains ({block})"
        if self.cautions:
            caut = ", ".join(c.value for c in self.cautions)
            return f"CLEARS at reduced confidence — cannot exclude: {caut}"
        return "CLEARS at HIGH confidence — all innocent explanations ruled out"


def run_ach(claim: str, assessments: list[AltAssessment]) -> ACHResult:
    """
    Apply the deterministic ACH gate to a claim given the agent's assessments.
      - completeness: all four REQUIRED_CATEGORIES must be present
      - blocking:     any 'plausible' alternative blocks the claim
      - cautions:     any 'cannot_exclude' lowers confidence (does not block)
      - clears = complete AND nothing blocking
    """
    present = {a.category for a in assessments}
    missing = [c for c in REQUIRED_CATEGORIES if c not in present]
    blocking = [a.category for a in assessments if a.disposition == Disposition.PLAUSIBLE]
    cautions = [a.category for a in assessments if a.disposition == Disposition.CANNOT_EXCLUDE]

    clears = (not missing) and (not blocking)
    if not clears:
        confidence = "blocked"
    elif cautions:
        confidence = "reduced"
    else:
        confidence = "high"

    return ACHResult(
        claim=claim,
        assessments=assessments,
        missing_categories=missing,
        blocking=blocking,
        cautions=cautions,
        clears=clears,
        confidence=confidence,
    )


def run_ach_stage(memory, claim: str, assessments: list[AltAssessment]) -> ACHResult:
    """
    The box-6.7 stage the loop calls. Runs the gate and logs the outcome into
    case memory so it flows to 6.8 and the report. Returns the result so the loop
    can decide whether the claim may support a conclusion.
    """
    result = run_ach(claim, assessments)
    memory.log("ach", f"ACH[{claim}] -> {result.confidence.upper()}: {result.verdict()}")
    return result