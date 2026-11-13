"""
diagnose_tools.py — call each forensic tool DIRECTLY on the real capture files and
print what it actually returns. No LLM. This tells us WHY the agent saw "empty".

Usage (on the VM):
    python diagnose_tools.py ~/Uju/AndroidEraser2
"""
import json
import sys

import main as m
from tools.registry import build_catalog

TYPE_TO_TOOL = {
    "usage_stats": "read_usagestats",
    "logcat": "read_logcat",
    "shared_prefs": "read_sharedprefs",
}


def summarize(kind: str, result: dict) -> str:
    """A short, human-readable summary of what the tool returned."""
    if not isinstance(result, dict):
        return f"(non-dict result: {type(result).__name__})"
    status = result.get("status")
    if kind == "usage_stats":
        return (f"status={status}  packages={len(result.get('packages', []))}  "
                f"events={len(result.get('events', []))}  note={result.get('note','')}")
    if kind == "logcat":
        return (f"status={status}  total_lines={result.get('total_lines')}  "
                f"match_count={result.get('match_count')}  "
                f"file_paths={len(result.get('file_paths', []))}  note={result.get('note','')}")
    if kind == "shared_prefs":
        return (f"status={status}  entries={len(result.get('entries', []))}  "
                f"note={result.get('note','')}")
    return f"status={status}"


def main() -> None:
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    catalog = build_catalog()
    inventory = m.scan_capture(folder)
    print(f"Found {len(inventory)} artifact file(s) in {folder}\n")

    for item in inventory:
        kind, path = item["type"], item["path"]
        tool = catalog.get(TYPE_TO_TOOL[kind])
        print("=" * 72)
        print(f"{kind}  ->  {path}")
        try:
            raw = tool.handler(artifact_path=path)
        except Exception as exc:
            print(f"  !! TOOL RAISED: {type(exc).__name__}: {exc}")
            continue
        print("  SUMMARY:", summarize(kind, raw))
        # show the first chunk of the raw result so we can see the real shape
        blob = json.dumps(raw, ensure_ascii=False, default=str)
        print("  RAW (first 800 chars):")
        print("   ", blob[:800])
        print()


if __name__ == "__main__":
    main()