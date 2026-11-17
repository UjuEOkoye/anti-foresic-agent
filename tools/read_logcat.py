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
  3. OVERVIEW (when no pattern is given — added 2026-11-17, Fix 2): the agent
     cannot know what to search for until it has seen the log, and with no
     pattern the tool used to return NO lines at all, so the log was invisible
     (live run #2 concluded "no file-operation evidence in logcat" although the
     dump holds 58 'Clearing DocumentFile' lines). Now a no-pattern call returns
     a compact summary: the most frequent message TEMPLATES (numbers/paths
     blanked so similar lines group), the templates that reference FILE PATHS,
     and the most active log tags — all with counts. Still generic: it
     summarises whatever is there and knows no app. The agent then calls again
     WITH a pattern to pull the exact lines as citable evidence.

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

# ---- overview (no-pattern call) ---------------------------------------------
# Sizes keep the overview small enough for the agent's compact view.
_OVERVIEW_TOP_TEMPLATES = 10
_OVERVIEW_PATH_TEMPLATES = 10
_OVERVIEW_TOP_TAGS = 10
_TEMPLATE_MAX_LEN = 100

# Standard logcat line shapes (no app knowledge — just the log format):
#   threadtime: "05-13 16:20:01.200  1234  1250 D Tag: message"
#   brief     : "D/Tag( 1234): message"
# NOT anchored to the start of the line: exported "hits" files often carry a
# prefix before the logcat line (e.g. "C:\\...\\dump.txt:123:" from a search
# tool). Matching anywhere finds the real logcat line inside such a prefix.
_THREADTIME_RE = re.compile(
    r"\d\d-\d\d\s+\d\d:\d\d:\d\d\.\d+\s+\d+\s+\d+\s+[VDIWEF]\s+([^:]+?)\s*:\s?(.*)$")
_BRIEF_RE = re.compile(r"(?:^|\s)[VDIWEF]/([^(:]+?)\s*\(\s*\d+\):\s?(.*)$")
# For TEMPLATES only: a file name may contain spaces ("WhatsApp Image 2024-05-01
# at 10.20.30 (1).jpeg"). _PATH_RE stops at the first space, so such lines split
# into many templates. This variant lets the path run on, across spaces, up to the
# nearest token that ends in a file extension containing a letter (".jpeg", not
# ".30"). If no such token follows, it is just the plain path (e.g. "chatty ...
# /system/bin/audioserver expire 3 lines" is unchanged). Generic path syntax only.
_TEMPLATE_PATH_RE = re.compile(
    _PATH_RE.pattern
    + r"(?:\s+[^\s\"'<>|]+)*?\.(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,5}(?=\s|$)"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{8,}\b")
_NUM_RE = re.compile(r"\d+")
_PATH_TOKEN = "<path>"


def _split_tag(line: str) -> tuple[str, str]:
    """Return (tag, message) for a standard logcat line, else ("", line)."""
    for rx in (_THREADTIME_RE, _BRIEF_RE):
        m = rx.search(line)
        if m:
            return m.group(1).strip(), m.group(2)
    return "", line


def _template(tag: str, message: str) -> str:
    """Blank out the parts that vary (paths, hex ids, numbers) so similar lines group."""
    msg = _TEMPLATE_PATH_RE.sub(_PATH_TOKEN, message)   # file names with spaces first
    msg = _PATH_RE.sub(_PATH_TOKEN, msg)                  # then any remaining plain paths
    msg = _HEX_RE.sub("<id>", msg)
    msg = _NUM_RE.sub("<n>", msg)
    msg = " ".join(msg.split())
    text = f"{tag}: {msg}" if tag else msg
    return text[:_TEMPLATE_MAX_LEN]


def _overview(lines: list[str]) -> dict:
    """Compact, generic summary of a log: frequent templates, path templates, tags."""
    from collections import Counter
    templates: Counter = Counter()
    tags: Counter = Counter()
    for line in lines:
        if not line.strip():
            continue
        tag, msg = _split_tag(line)
        if tag:
            tags[tag] += 1
        templates[_template(tag, msg)] += 1
    path_templates = [(t, c) for t, c in templates.most_common() if _PATH_TOKEN in t]
    return {
        "distinct_templates": len(templates),
        # most relevant first: lines that reference files
        "file_path_templates": [{"template": t, "count": c}
                                for t, c in path_templates[:_OVERVIEW_PATH_TEMPLATES]],
        "top_tags": [{"tag": t, "count": c} for t, c in tags.most_common(_OVERVIEW_TOP_TAGS)],
        "top_templates": [{"template": t, "count": c}
                          for t, c in templates.most_common(_OVERVIEW_TOP_TEMPLATES)],
        "how_to_use": "call read_logcat again WITH a pattern (e.g. a phrase from a template) "
                      "to retrieve the exact lines as citable evidence",
    }


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

    if not pattern:
        note += " No pattern given: see 'overview', then search WITH a pattern."

    # Key order matters: the agent's compact view is length-capped, so the most
    # useful parts come first and the long file_paths list comes last.
    result = {
        "status": "ok",
        "artifact_path": artifact_path,
        "pattern": pattern,
        "total_lines": len(lines),
        "match_count": match_count,
        "note": note,
    }
    if not pattern:
        result["overview"] = _overview(lines)
    result["matches"] = matches
    result["file_paths"] = file_paths
    return result


READ_LOGCAT = ToolSchema(
    name="read_logcat",
    purpose=(
        "Read an Android logcat text dump. Call it FIRST WITHOUT a pattern to get an "
        "overview (most frequent message templates with counts, templates that "
        "reference file paths, most active log tags). Then call it again WITH a "
        "pattern (regex or literal substring) to retrieve the exact matching lines "
        "as citable evidence. Always extracts filesystem paths referenced in the "
        "log. Generic: it summarises and greps; it does not interpret or know any app."
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
        FieldSpec(name="overview", field_type=FieldType.OBJECT,
                  description="no-pattern calls only: frequent templates, file-path templates, top tags"),
    ],
    handler=_read_logcat,
)