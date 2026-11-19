"""
Tool: read_sharedprefs

A GENERIC forensic reader for Android SharedPreferences XML files.

It reads ALL key-value pairs from a given shared_prefs XML file and returns them,
along with provenance (the artifact path). It does NOT know which app it is, which
keys matter, or what any value means — that interpretation is the agent's job.

This genericity is deliberate and protects the project's core novelty: detection
must be behavior-based and generalize to unknown tools. A tool that knew
app-specific keys would be a disguised known-app list.

Reuses the proven reading approach from CleanerScope's Get-XmlPreferenceValues
(rewritten in Python). Root-agnostic: it reads whatever path it is given. If the
file is missing or unreadable (e.g. app-private storage on a non-rooted device),
it returns an explicit NOT-ACCESSIBLE result — never a silent empty success —
because "could not access" and "accessed, found nothing" mean very different
things forensically (the acquisition-limits distinction).
"""

from __future__ import annotations
import os
import xml.etree.ElementTree as ET

from engine.tool_schema import ToolSchema, FieldSpec, FieldType


# ---- embedded-JSON decoding (2026-11-19) ---------------------------------------
# Apps often store structured records as JSON TEXT inside a preference value
# (one long string). The agent's compact view cuts every value at 300 characters,
# so the decisive fields of such a record (e.g. a success flag, byte totals, the
# list of items) were never visible to it — in the real AndroidEraser2 capture the
# agent saw only the first ~300 of 6,115 characters and concluded the record "may
# be a never-executed configuration". This decodes any JSON objects found inside a
# value (generic: no field or app names), and builds a SHORT structural summary:
# scalar fields as stored, lists as {count, first items}. The full value stays in
# 'entries' and in the audit store; the summary is placed first so the agent sees it.
import json as _json

_SUMMARY_LIST_ITEMS = 3
_SUMMARY_STR_MAX = 120


def _decode_embedded_json(text: str) -> list:
    """Every JSON object/array found inside a string, in order (skips separators)."""
    if not isinstance(text, str) or ("{" not in text and "[" not in text):
        return []
    dec, i, out = _json.JSONDecoder(), 0, []
    while i < len(text):
        if text[i] in "{[":
            try:
                obj, j = dec.raw_decode(text, i)
                if isinstance(obj, (dict, list)):
                    out.append(obj)
                    i = j
                    continue
            except _json.JSONDecodeError:
                pass
        i += 1
    return out


def _summarize(value, depth: int = 0):
    """Structure-preserving summary: scalars as stored, lists as {count, first}."""
    if isinstance(value, dict):
        if depth >= 3:
            return {"keys": list(value)[:10]}
        return {k: _summarize(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return {"count": len(value),
                "first": [_summarize(v, depth + 1) for v in value[:_SUMMARY_LIST_ITEMS]]}
    if isinstance(value, str) and len(value) > _SUMMARY_STR_MAX:
        return value[:_SUMMARY_STR_MAX] + "...[cut]"
    return value


# ---- the handler: the function that actually does the work --------------------

def _read_sharedprefs(artifact_path: str) -> dict:
    """
    Read every key-value pair from an Android shared_prefs XML file.

    Returns a structured result dict. 'status' tells the agent what happened:
      - "ok"            : file read, entries returned (possibly zero entries)
      - "not_found"     : the path does not exist (e.g. non-rooted acquisition limit)
      - "unreadable"    : the path exists but could not be read/parsed
    The agent MUST treat "not_found"/"unreadable" as an acquisition limitation,
    not as evidence that no anti-forensic activity occurred.
    """
    # 1. Does the file exist at all? (non-rooted access often fails here)
    if not os.path.isfile(artifact_path):
        return {
            "status": "not_found",
            "artifact_path": artifact_path,
            "entries": {},
            "note": "File not present or not accessible (possible acquisition limitation).",
        }

    # 2. Try to parse the XML and pull out every <... name="..." value="..."/> entry.
    try:
        tree = ET.parse(artifact_path)
        root = tree.getroot()  # the <map> element in an Android prefs file
    except Exception as exc:
        return {
            "status": "unreadable",
            "artifact_path": artifact_path,
            "entries": {},
            "note": f"File present but could not be parsed as XML: {exc}",
        }

    # 3. Collect ALL key-value pairs — no filtering, no app-specific knowledge.
    entries: dict[str, str] = {}
    for node in root:
        name = node.attrib.get("name")
        if name is None:
            continue
        # Android stores the value either as a 'value' attribute (int/bool/float)
        # or as the element's inner text (strings). Capture whichever is present.
        if "value" in node.attrib:
            entries[name] = node.attrib["value"]
        else:
            entries[name] = (node.text or "").strip()

    # 4. Decode structured records stored as JSON text inside values (see above).
    decoded = {k: objs for k, v in entries.items() if (objs := _decode_embedded_json(v))}
    summary = {k: {"records": len(objs), "records_summary": [_summarize(o) for o in objs]}
               for k, objs in decoded.items()}

    return {
        "status": "ok",
        "artifact_path": artifact_path,
        # placed BEFORE 'entries' so it stays inside the agent's compact view
        "decoded_json_summary": summary,
        "entries": entries,
        "decoded_json": decoded,          # full decoded records (also in the audit store)
        "note": (f"Read {len(entries)} preference entries"
                 + (f"; decoded JSON records inside: {', '.join(f'{k} ({len(o)})' for k, o in decoded.items())}"
                    if decoded else "") + "."),
    }


# ---- the schema: the tool's "ID card" that the agent and engine use -----------

READ_SHAREDPREFS = ToolSchema(
    name="read_sharedprefs",
    purpose=(
        "Read all key-value pairs from an Android SharedPreferences XML file at a "
        "given path. Use to inspect an app's stored settings/state. Returns raw "
        "entries for you to interpret; it does not judge whether they are "
        "anti-forensic."
    ),
    args=[
        FieldSpec(
            name="artifact_path",
            field_type=FieldType.STRING,
            description="Filesystem path to the shared_prefs XML file to read.",
            required=True,
        ),
    ],
    output=[
        FieldSpec(
            name="status",
            field_type=FieldType.STRING,
            description="ok | not_found | unreadable",
            allowed_values=["ok", "not_found", "unreadable"],
        ),
        FieldSpec(
            name="artifact_path",
            field_type=FieldType.STRING,
            description="The path that was read (provenance / chain of custody).",
        ),
        FieldSpec(
            name="entries",
            field_type=FieldType.OBJECT,
            description="All recovered key-value pairs (key -> value as strings).",
        ),
        FieldSpec(
            name="note",
            field_type=FieldType.STRING,
            description="Human-readable summary of what happened.",
        ),
    ],
    handler=_read_sharedprefs,
)