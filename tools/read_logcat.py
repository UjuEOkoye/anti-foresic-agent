"""
tools/read_logcat.py

A box-6.5 forensic tool: read an Android logcat text dump.

logcat is a large plain-text log. This tool does NOT interpret it and does NOT
know anything about any app. It does two generic things:
  1. SEARCH: return lines matching a `pattern` the AGENT supplies (regex, or a
     literal substring if the pattern isn't valid regex). The agent decides what
     to look for; the tool just greps.
  2. PATH EXTRACTION: generically pull anything that looks like an Android/Unix
     filesystem path (/storage/..., /data/..., /sdcard/..., etc.) out of every
     line, deduped. This surfaces "which files were referenced" without any
     app-specific knowledge.

"not_found" is a first-class result (an acquisition limit, NOT proof of a clean
device). Large dumps are fine — the dual-output layer (6.5) shrinks what the LLM
sees; this tool returns the real matches + paths for the audit store.
"""

import os
import re

from engine.tool_schema import FieldType, FieldSpec, ToolSchema


# Generic absolute-path shapes seen on Android. No app knowledge — just path syntax.
_PATH_RE = re.compile(r"/(?:storage|sdcard|data|mnt|system)/[^\s\"'<>|]+")

def _decode_log_bytes(data: bytes) -> str:
    """
    Decode a log file that might be UTF-8 or UTF-16 (Windows logcat dumps are
    often UTF-16). Honors a BOM; otherwise sniffs for UTF-16 by counting NUL
    bytes. Always returns text (never raises).
    """
    if data[:3] == b"\xef\xbb\xbf":            # UTF-8 BOM
        return data[3:].decode("utf-8", errors="replace")
    if data[:2] == b"\xff\xfe":                # UTF-16 LE BOM
        return data[2:].decode("utf-16-le", errors="replace")
    if data[:2] == b"\xfe\xff":                # UTF-16 BE BOM
        return data[2:].decode("utf-16-be", errors="replace")
    # No BOM: if a sample is full of NUL bytes, it's almost certainly UTF-16
    sample = data[:4096]
    if sample.count(b"\x00") > len(sample) // 4:
        codec = "utf-16-le" if sample[1::2].count(0) >= sample[0::2].count(0) else "utf-16-be"
        return data.decode(codec, errors="replace")
    return data.decode("utf-8", errors="replace")

# How many matching lines to return at most (full raw still lives in the dump).
_DEFAULT_MAX_MATCHES = 200


def _read_logcat(artifact_path, pattern=None, max_matches=_DEFAULT_MAX_MATCHES):
    """Read a logcat text file. Returns a dict; never raises on bad input."""
    if not os.path.exists(artifact_path):
        return {
            "status": "not_found",
            "artifact_path": artifact_path,
            "pattern": pattern,
            "total_lines": 0,
            "match_count": 0,
            "matches": [],
            "file_paths": [],
            "note": ("logcat file not found at this path — an acquisition limit, "
                     "NOT proof of a clean device."),
        }

    try:
        with open(artifact_path, "rb") as fh:          # read bytes, decode smartly
            lines = _decode_log_bytes(fh.read()).splitlines()
    except Exception as exc:
        return {
            "status": "unreadable",
            "artifact_path": artifact_path,
            "pattern": pattern,
            "total_lines": 0,
            "match_count": 0,
            "matches": [],
            "file_paths": [],
            "note": f"could not read logcat file: {exc}",
        }

    # 1. SEARCH for the agent-supplied pattern (if any)
    matches = []
    match_count = 0
    if pattern:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
            test = rx.search
        except re.error:
            # pattern wasn't valid regex -> treat it as a literal substring
            needle = pattern.lower()
            test = lambda line: needle in line.lower()
        for i, line in enumerate(lines, start=1):
            if test(line):
                match_count += 1
                if len(matches) < max_matches:
                    matches.append({"line": i, "text": line})

    # 2. generic file-path extraction across the WHOLE log, deduped (order kept)
    seen = set()
    file_paths = []
    for line in lines:
        for hit in _PATH_RE.findall(line):
            if hit not in seen:
                seen.add(hit)
                file_paths.append(hit)

    note = f"read {len(lines)} line(s); extracted {len(file_paths)} unique path(s)."
    if pattern:
        note += f" {match_count} line(s) matched the pattern"
        if match_count > len(matches):
            note += f" (showing first {len(matches)})"
        note += "."

    return {
        "status": "ok",
        "artifact_path": artifact_path,
        "pattern": pattern,
        "total_lines": len(lines),
        "match_count": match_count,
        "matches": matches,
        "file_paths": file_paths,
        "note": note,
    }


READ_LOGCAT = ToolSchema(
    name="read_logcat",
    purpose=(
        "Read an Android logcat text dump. Optionally return lines matching a "
        "caller-supplied pattern (regex or literal substring), and always extract "
        "any Android/Unix filesystem paths referenced in the log. Generic: it "
        "greps and extracts; it does not interpret the log or know any app."
    ),
    args=[
        FieldSpec(
            name="artifact_path",
            field_type=FieldType.STRING,
            description="Path to a logcat text file (e.g. 01_logcat_full_dump_afterwipe.txt).",
            required=True,
        ),
        FieldSpec(
            name="pattern",
            field_type=FieldType.STRING,
            description="Optional search pattern (regex, or literal substring if not valid regex).",
            required=False,
        ),
    ],
    output=[
        FieldSpec(name="status", field_type=FieldType.STRING,
                  description="ok | not_found | unreadable"),
        FieldSpec(name="matches", field_type=FieldType.LIST,
                  description="lines matching the pattern ({line, text})"),
        FieldSpec(name="file_paths", field_type=FieldType.LIST,
                  description="unique filesystem paths referenced in the log"),
    ],
    handler=_read_logcat,
)