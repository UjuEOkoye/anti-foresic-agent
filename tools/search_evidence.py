"""
tools/search_evidence.py

A box-5 / 6.5 helper tool: search INSIDE a piece of evidence that has already
been collected and preserved in the audit store (the full raw record, not the
compact view the agent normally sees).

Why (Fix G, 2026-11-17): the agent's view of each result is compact — long values
are cut at 300 characters ("...[truncated; see audit store]"). In live run #6 the
wipe report's file list sat past that cut, so the agent could not see (or quote)
the file names, and the strongest corroboration — the same names in the report
and in the system log — was lost. This tool lets the agent look up exactly what it
needs inside the full record, by an agent-supplied pattern, and get back short
snippets plus where they came from (the field path).

Design rules (same as every tool here):
  - GENERIC: knows nothing about any app; it searches whatever text is there.
  - READ-ONLY: never changes the preserved evidence; it reads the audit store.
  - Its own result is preserved like any tool result (it gets its own evidence id),
    and its snippets are exact substrings of the original record (verbatim).

"Pipeline: box 5 says compact view for reasoning, full evidence preserved AND
selectively retrievable" — this is the "selectively retrievable" part.
"""
from __future__ import annotations

import re
from typing import Any

from engine.tool_schema import FieldType, FieldSpec, ToolSchema

_DEFAULT_MAX_HITS = 20
_CONTEXT_CHARS = 80


def _walk(value: Any, path: str = ""):
    """Yield (field_path, text) for every string/number inside a raw record."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")
    elif value is not None:
        yield path, str(value)


def make_search_evidence_tool(audit_store) -> ToolSchema:
    """Build the tool bound to ONE investigation's audit store."""

    def _search_evidence(evidence_id: str, pattern: str, max_hits: int = _DEFAULT_MAX_HITS) -> dict:
        try:
            record = audit_store.get(evidence_id)
        except KeyError:
            return {"status": "not_found", "evidence_id": evidence_id, "pattern": pattern,
                    "hits": [], "note": f"no evidence with id {evidence_id} has been collected"}
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(pattern), re.IGNORECASE)

        hits: list[dict] = []
        total = 0
        for field_path, text in _walk(record["raw"]):
            for m in rx.finditer(text):
                total += 1
                if len(hits) < max_hits:
                    a = max(0, m.start() - _CONTEXT_CHARS)
                    b = min(len(text), m.end() + _CONTEXT_CHARS)
                    hits.append({"field": field_path,
                                 "snippet": text[a:b]})        # exact substring (verbatim)
        note = f"{total} match(es) in the full record of {evidence_id} ({record['tool']})"
        if total > len(hits):
            note += f"; showing the first {len(hits)}"
        return {"status": "ok", "evidence_id": evidence_id, "source_tool": record["tool"],
                "pattern": pattern, "match_count": total, "note": note, "hits": hits}

    return ToolSchema(
        name="search_evidence",
        purpose=(
            "Search INSIDE evidence you already collected (by its evidence id, e.g. E0002), "
            "in the FULL preserved record — use it when a value in your view was cut off "
            "('...[truncated]'). Returns exact snippets (with their field path) matching a "
            "pattern (regex or literal). Snippets are verbatim, so you can quote them."
        ),
        args=[
            FieldSpec(name="evidence_id", field_type=FieldType.STRING,
                      description="id of evidence already collected, e.g. E0002", required=True),
            FieldSpec(name="pattern", field_type=FieldType.STRING,
                      description="text or regex to find inside that evidence", required=True),
        ],
        output=[
            FieldSpec(name="hits", field_type=FieldType.LIST,
                      description="matches: {field, snippet} — snippet is verbatim text"),
            FieldSpec(name="match_count", field_type=FieldType.INTEGER,
                      description="total matches in the full record"),
        ],
        handler=_search_evidence,
    )