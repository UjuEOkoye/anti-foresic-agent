"""
engine/correlation.py

Pipeline BOX 6.6 — Correlation + Consistency + Expected-Artifact / Absence Analysis.

Two deterministic jobs (no LLM in this file):

1. CORRELATION across sources
   - CORROBORATION: the same fact seen in >= 2 independent sources is stronger
     than seen once (e.g. the same wiped filename in BOTH shared_prefs AND logcat).
   - CONFLICT: two sources that disagree about the same thing — a tool that
     hides/fakes something can't fake everything consistently.

2. EXPECTED-ARTIFACT / ABSENCE ANALYSIS  (the W1 crown jewel)
   - Compare what SHOULD be present vs what WAS found. Expected-but-missing = flagged.
   - RULE ENFORCED IN CODE: "missing != automatically deleted." A missing artifact
     gets a LIST of candidate explanations. This box only IDENTIFIES the gap and
     lists candidates; box 6.7 (ACH) tests and rules them out. We never conclude
     "deleted" here.

MECHANISM / COGNITION SPLIT:
  - The AGENT (LLM, later) extracts Observations from raw evidence and decides
    which artifacts to EXPECT.
  - THIS FILE does the deterministic grouping + set-difference. Deterministic =
    testable, reproducible (RQ5), ablatable (RQ4).
"""

from __future__ import annotations
from dataclasses import dataclass, field


# Candidate explanations for a MISSING artifact. Listed here, RESOLVED in 6.7 (ACH).
# The order is deliberate: innocent explanations first, so "deleted" is never the
# default assumption. This list is literally the "missing != deleted" rule.
ABSENCE_EXPLANATIONS = [
    "acquisition_limit: the artifact may simply not have been captured",
    "never_existed: the artifact may never have been created",
    "normal_removal: ordinary uninstall / cache-clear / reboot removed it",
    "possible_anti_forensic_removal: it may have been deliberately wiped or hidden",
]


@dataclass
class Observation:
    """
    One concrete fact the agent extracted from a piece of evidence. The agent
    (LLM) produces these from raw tool output; this file only correlates them.
      source_id : the audit-store evidence id the fact came from (E0001, ...)
      claim_key : WHAT the fact is about ('wiped_file', 'wipe_method',
                  'device_timezone') — the shared label that lets two sources
                  be compared
      value     : the concrete value ('report_2024.pdf')
    """
    source_id: str
    claim_key: str
    value: str


@dataclass
class Corroboration:
    """One claim_key+value confirmed by two or more independent sources."""
    claim_key: str
    value: str
    sources: list[str]


@dataclass
class Conflict:
    """One claim_key where sources disagree (>= 2 distinct values)."""
    claim_key: str
    values_by_source: dict[str, str]   # source_id -> the value it reported


@dataclass
class ExpectedArtifact:
    """
    Something the agent expects for the behavior it suspects.
      label   : human description ('shared_prefs for the wiping app')
      locator : the identifier we check presence against (an artifact_path or key)
      reason  : why it is expected (for the report / audit trail)
    """
    label: str
    locator: str
    reason: str = ""


@dataclass
class Absence:
    """An expected artifact that was NOT found. NOT a verdict that it was deleted."""
    label: str
    locator: str
    reason: str
    candidate_explanations: list[str] = field(
        default_factory=lambda: list(ABSENCE_EXPLANATIONS)
    )


@dataclass
class CorrelationResult:
    """Everything box 6.6 produced in one pass."""
    corroborations: list[Corroboration]
    conflicts: list[Conflict]
    absences: list[Absence]


# --- the two deterministic analyses (pure functions) -------------------------

def correlate(observations: list[Observation]) -> tuple[list[Corroboration], list[Conflict]]:
    """
    Group observations by claim_key. For each key:
      - a single value backed by >= 2 distinct sources  -> corroboration
      - >= 2 distinct values (sources disagree)          -> conflict
    Pure grouping + comparison. No interpretation.
    """
    # claim_key -> { value -> set(source_ids) }
    grouped: dict[str, dict[str, set[str]]] = {}
    for obs in observations:
        grouped.setdefault(obs.claim_key, {}).setdefault(obs.value, set()).add(obs.source_id)

    corroborations: list[Corroboration] = []
    conflicts: list[Conflict] = []

    for claim_key, value_map in grouped.items():
        # corroboration: any one value backed by two or more distinct sources
        for value, sources in value_map.items():
            if len(sources) >= 2:
                corroborations.append(
                    Corroboration(claim_key=claim_key, value=value, sources=sorted(sources))
                )
        # conflict: the same claim_key carries two or more distinct values
        if len(value_map) >= 2:
            values_by_source: dict[str, str] = {}
            for value, sources in value_map.items():
                for s in sources:
                    values_by_source[s] = value
            conflicts.append(Conflict(claim_key=claim_key, values_by_source=values_by_source))

    return corroborations, conflicts


def absence_analysis(expected: list[ExpectedArtifact],
                     present_locators: set[str]) -> list[Absence]:
    """
    Expected vs present. Any expected artifact whose locator is NOT present is an
    Absence carrying candidate explanations. We never conclude 'deleted' here.
    """
    return [
        Absence(label=art.label, locator=art.locator, reason=art.reason)
        for art in expected
        if art.locator not in present_locators
    ]


# --- the box-6.6 stage the loop calls ----------------------------------------

def run_correlation(memory, observations: list[Observation],
                    expected: list[ExpectedArtifact],
                    present_locators: set[str]) -> CorrelationResult:
    """
    Run both analyses and write the results back into case memory (so they flow
    to 6.7 and the report), then return them.
      - corroborations / conflicts  -> logged in case memory
      - each absence -> recorded as a NegativeIndicator with suspicious=True,
        meaning 'warrants investigation in 6.7' — NOT 'proven deleted'.
    """
    corroborations, conflicts = correlate(observations)
    absences = absence_analysis(expected, present_locators)

    for c in corroborations:
        memory.log("correlation",
                   f"CORROBORATED {c.claim_key}={c.value} by {', '.join(c.sources)}")
    for cf in conflicts:
        memory.log("correlation", f"CONFLICT on {cf.claim_key}: {cf.values_by_source}")
    for ab in absences:
        memory.record_absence(
            looked_for=ab.label,
            location=ab.locator,
            suspicious=True,   # warrants investigation in 6.7 — NOT a deletion verdict
            note="expected but absent; candidates: " + "; ".join(ab.candidate_explanations),
        )

    return CorrelationResult(corroborations=corroborations,
                             conflicts=conflicts,
                             absences=absences)