"""
engine/self_verification.py

Pipeline BOX 6.8 — Self-Verification. The agent's final self-audit before it is
allowed to conclude. Almost entirely deterministic (no LLM): it checks the case
memory against the audit store by fixed rules.

TWO CHECKS:
  1. GROUNDING — every Finding must cite evidence_ids that ACTUALLY EXIST in the
     audit store. A finding citing a missing/hallucinated id is FLAGGED and must
     not reach the report. (Anti-hallucination backstop.)
  2. HYPOTHESIS RESOLUTION —
       - an OPEN hypothesis that now has a grounded supporting finding is
         upgraded to CONFIRMED (closes the 'H0001 stayed open' gap).
       - a hypothesis marked CONFIRMED with NO supporting grounded finding is
         FLAGGED (confirmed without evidence).

If any flags come back, the investigation is NOT clean — those claims are kicked
back rather than reported.

Deterministic = testable (RQ5) + ablatable (RQ4).
"""

from __future__ import annotations
from dataclasses import dataclass, field

from engine.case_memory import HypothesisStatus


@dataclass
class VerificationFlag:
    """One problem found during self-verification."""
    kind: str        # "ungrounded_finding" | "confirmed_without_support"
    subject_id: str  # the finding_id or hyp_id it concerns
    detail: str


@dataclass
class VerificationResult:
    flags: list[VerificationFlag]
    ready_to_confirm: list[str]   # OPEN hyp_ids that have grounded support
    verified: bool                # True iff no flags
    checked_findings: int


def _evidence_exists(audit_store, evidence_id: str) -> bool:
    """Does this evidence id actually exist in the audit store?"""
    try:
        audit_store.get(evidence_id)
        return True
    except KeyError:
        return False


def verify(memory, audit_store) -> VerificationResult:
    """Run both checks. Pure inspection — does NOT mutate case memory."""
    flags: list[VerificationFlag] = []
    findings = memory.findings_list()

    # 1. GROUNDING: every cited evidence id must exist in the audit store.
    for f in findings:
        for ev in f.evidence_ids:
            if not _evidence_exists(audit_store, ev):
                flags.append(VerificationFlag(
                    kind="ungrounded_finding",
                    subject_id=f.finding_id,
                    detail=f"cites {ev}, which is not in the audit store",
                ))

    # Which hypotheses have at least one FULLY-grounded supporting finding?
    supported: set[str] = set()
    for f in findings:
        if f.hypothesis_id and f.evidence_ids and all(
            _evidence_exists(audit_store, ev) for ev in f.evidence_ids
        ):
            supported.add(f.hypothesis_id)

    # 2. HYPOTHESIS RESOLUTION
    ready_to_confirm: list[str] = []
    for h in memory.all_hypotheses():
        has_support = h.hyp_id in supported
        if h.status == HypothesisStatus.CONFIRMED and not has_support:
            flags.append(VerificationFlag(
                kind="confirmed_without_support",
                subject_id=h.hyp_id,
                detail="marked confirmed but no grounded finding supports it",
            ))
        if h.status == HypothesisStatus.OPEN and has_support:
            ready_to_confirm.append(h.hyp_id)

    return VerificationResult(
        flags=flags,
        ready_to_confirm=ready_to_confirm,
        verified=(len(flags) == 0),
        checked_findings=len(findings),
    )


def run_self_verification(memory, audit_store, auto_confirm: bool = True) -> VerificationResult:
    """
    The box-6.8 stage the loop calls. Runs the checks, logs them into case memory,
    and (if auto_confirm) upgrades supported-but-open hypotheses to CONFIRMED.
    Returns the result so the loop can refuse to conclude when verified is False.
    """
    result = verify(memory, audit_store)

    for flag in result.flags:
        memory.log("self_verification", f"FLAG {flag.kind} [{flag.subject_id}]: {flag.detail}")

    for hyp_id in result.ready_to_confirm:
        if auto_confirm:
            memory.confirm_hypothesis(
                hyp_id, reason="self-verification: supported by grounded finding(s)"
            )
        else:
            memory.log("self_verification", f"{hyp_id} ready to confirm (has grounded support)")

    memory.log(
        "self_verification",
        f"VERIFIED={result.verified} "
        f"({len(result.flags)} flag(s); {result.checked_findings} finding(s) checked)",
    )
    return result