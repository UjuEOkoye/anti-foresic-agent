"""
Dual-output handler.

Every tool result is kept in TWO forms:
  - FULL RAW : the complete, unmodified result, preserved in the audit store with
               an ID and an integrity hash. This is what the final report CITES.
  - PROJECTED: a compact, VERBATIM subset of the result (only the fields relevant
               to the current step). This is what the agent REASONS over.

Guiding principle: "reduce what the LLM sees, not what the evidence contains."
The projected view is a true subset of the real values — NEVER a paraphrase — so
the agent reasons over smaller but truthful data while the complete original is
always preserved for court-defensibility and chain of custody.
"""

from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


# ---- the audit store: where full-raw results are preserved --------------------

@dataclass
class AuditStore:
    """
    Holds the complete, unmodified output of every tool call. Each entry gets a
    stable ID and an integrity hash. The report references evidence by these IDs;
    the agent's reasoning never loads these full blobs directly.
    """
    _records: dict[str, dict] = field(default_factory=dict)
    _counter: int = 0

    def store(self, tool_name: str, raw_result: Any) -> dict:
        """
        Preserve a full raw result. Returns a small receipt the agent/report can
        reference: {evidence_id, tool, hash}.
        """
        self._counter += 1
        evidence_id = f"E{self._counter:04d}"   # E0001, E0002, ...

        # Serialize deterministically so the hash is stable and reproducible.
        serialized = json.dumps(raw_result, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        self._records[evidence_id] = {
            "evidence_id": evidence_id,
            "tool": tool_name,
            "hash": digest,
            "raw": raw_result,     # the complete, untouched result
        }
        return {"evidence_id": evidence_id, "tool": tool_name, "hash": digest}

    def get(self, evidence_id: str) -> dict:
        """Retrieve a full raw record by its ID (used when building the report)."""
        return self._records[evidence_id]

    def __len__(self) -> int:
        return len(self._records)


# ---- projection: make a compact, verbatim view for reasoning ------------------

# When no field list is given, long string values are truncated to this many chars
# so a single huge value (like savekey_reports) can't flood the context window.
DEFAULT_MAX_VALUE_LEN = 300


def _truncate_value(value: Any, max_len: int) -> Any:
    """
    Shorten an over-long value WITHOUT changing other values. For a long string,
    keep the first max_len characters and mark that it was truncated (so the agent
    knows the full version lives in the audit store).
    """
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f" ...[truncated, {len(value)} chars total; see audit store]"
    return value


def project(raw_result: Any, keep_fields: list[str] | None = None,
            max_value_len: int = DEFAULT_MAX_VALUE_LEN) -> Any:
    """
    Produce a compact, VERBATIM view of a raw result for the agent's reasoning.

    - If keep_fields is given and the result is a dict, keep ONLY those top-level
      fields (values copied exactly — no rewording).
    - If keep_fields is None, keep all fields but truncate over-long string values.
    - Nested over-long values are truncated the same way.

    This never paraphrases or invents values; it only selects and/or truncates.
    """
    # Non-dict results: just truncate if they're an over-long string.
    if not isinstance(raw_result, dict):
        return _truncate_value(raw_result, max_value_len)

    # Decide which keys to include.
    if keep_fields is not None:
        selected = {k: raw_result[k] for k in keep_fields if k in raw_result}
    else:
        selected = dict(raw_result)

    # Truncate over-long values (recurse one level into nested dicts).
    projected: dict[str, Any] = {}
    for k, v in selected.items():
        if isinstance(v, dict):
            projected[k] = {ik: _truncate_value(iv, max_value_len) for ik, iv in v.items()}
        else:
            projected[k] = _truncate_value(v, max_value_len)

    return projected


# ---- the combined handler: store full raw + return projected view -------------

@dataclass
class DualOutput:
    """Ties the two sides together: store full-raw, return a compact view + receipt."""
    audit: AuditStore = field(default_factory=AuditStore)

    def handle(self, tool_name: str, raw_result: Any,
               keep_fields: list[str] | None = None) -> dict:
        """
        Process one tool result.

        Returns what the agent should see next:
          - 'projected' : the compact verbatim view to reason over
          - 'evidence'  : the audit receipt (evidence_id + hash) proving the full
                          raw is preserved and citable in the report
        """
        receipt = self.audit.store(tool_name, raw_result)     # full raw -> audit
        projected = project(raw_result, keep_fields=keep_fields)  # compact view -> reasoning
        return {"projected": projected, "evidence": receipt}