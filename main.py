"""
main.py — the entry point. Assembles everything and runs ONE investigation on
ONE preserved Android capture folder.

Two modes:
  test  (default) — a fake, scripted reasoner. No GPU, no model. Proves the whole
                    system assembles and runs end-to-end. Runs on your laptop.
  live            — the real LLM reasoner (Qwen via Ollama on the VM). This is the
                    real investigation. Needs OLLAMA_* env vars + a reachable model.

Examples:
  python main.py --case "C:\\path\\to\\a\\capture\\folder"
  python main.py --case "/home/.../capture" --mode live
  OLLAMA_MODEL=qwen2.5:7b-instruct python main.py --case ./some_capture --mode live
"""
from __future__ import annotations
import argparse
import os
import re
from pathlib import Path

from engine.bounded_loop import (
    BoundedInvestigationLoop, FakeReasoner, AgentAction, ActionKind,
)
from engine.case_memory import CaseMemory
from engine.dual_output import DualOutput
from tools.registry import build_catalog
from tools.read_logcat import _decode_log_bytes
from knowledge_base import build_knowledge_base


# ---- box 3 (lite): scan the capture folder for recognised artifacts ----------

# ---- primary artifacts only (2026-11-17) --------------------------------------
# A capture folder can also hold files an ANALYST made from the evidence — e.g. a
# "hits" file of lines copied out of the logcat dump by a search tool. Such a file
# is not device evidence: (1) the agent would treat the copied lines as a second,
# independent source and "corroborate" a fact with itself; (2) it reveals what a
# human already chose to search for. Rule: the agent receives only PRIMARY artifacts
# the device produced. Detected by CONTENT, not by file name: a search-tool export
# prefixes each copied line with "<source file>:<line number>:" (or "<line number>:").
_COPIED_LINE_RE = re.compile(
    r"^(?:.{0,400}?[\\/][^\\/:]+\.[A-Za-z0-9]{1,6}:\d+:|\d+:)\s*\d\d-\d\d\s+\d\d:\d\d:\d\d"
)


def derived_reason(path: Path) -> str:
    """
    Return a reason string if this text file is an analyst-derived extract (most
    lines carry a "<file>:<line>:" copy prefix), else "" (a primary artifact).
    Reads only the first 256 KB. Never raises.
    """
    try:
        with open(path, "rb") as fh:
            text = _decode_log_bytes(fh.read(256 * 1024))
    except Exception:
        return ""
    sample = [ln for ln in text.splitlines() if ln.strip()][:50]
    if not sample:
        return ""
    copied = sum(1 for ln in sample if _COPIED_LINE_RE.match(ln))
    if copied / len(sample) >= 0.5:
        return (f"analyst-derived extract: {copied}/{len(sample)} sampled lines carry a "
                f"'<source file>:<line>:' copy prefix (not device-produced)")
    return ""


def scan_capture(folder: str) -> list[dict]:
    """
    Walk the capture folder and classify files into the artifact TYPES our tools
    read. Generic (by artifact type / path, never by app name). Returns a list of
    {"type": ..., "path": ...}.
    """
    root = Path(folder)
    inventory: list[dict] = []
    if not root.exists():
        return inventory
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        low = str(p).lower()
        name = p.name.lower()
        if "shared_prefs" in low and name.endswith(".xml"):
            kind = "shared_prefs"
        elif "usage_stats" in low or "usagestats" in low:
            # keep the informative daily buckets; skip the version marker and the
            # weekly/monthly/yearly rollups (they aggregate, they don't add detail).
            if name == "version" or p.parent.name.lower() in ("weekly", "monthly", "yearly"):
                continue
            kind = "usage_stats"
        elif "logcat" in name or (name.endswith(".txt") and "log" in low):
            kind = "logcat"
        else:
            continue
        item = {"type": kind, "path": str(p)}
        if kind == "logcat":
            reason = derived_reason(p)
            if reason:
                item["excluded"] = reason     # listed for transparency, never given to the agent
        inventory.append(item)
    return inventory


def format_excluded(inventory: list[dict]) -> str:
    """The files left out of the agent's input, with why (shown to the human only)."""
    excl = [i for i in inventory if i.get("excluded")]
    if not excl:
        return "(none)"
    return "\n".join(f"- {i['path']}\n    reason: {i['excluded']}" for i in excl)


def format_inventory(inventory: list[dict]) -> str:
    """The PRIMARY artifacts given to the agent (excluded files are left out)."""
    inventory = [i for i in inventory if not i.get("excluded")]
    if not inventory:
        return "(no recognised artifacts found in the capture folder)"
    by_type: dict[str, list[str]] = {}
    for item in inventory:
        by_type.setdefault(item["type"], []).append(item["path"])
    lines: list[str] = []
    for kind, paths in by_type.items():
        lines.append(f"- {kind} ({len(paths)} file(s)):")
        for path in paths[:10]:
            lines.append(f"    {path}")
        if len(paths) > 10:
            lines.append(f"    ...and {len(paths) - 10} more")
    return "\n".join(lines)


# ---- pick the brain ----------------------------------------------------------

def build_reasoner(mode: str, catalog):
    if mode == "live":
        from engine.llm_reasoner import LLMReasoner      # imported only when needed
        return LLMReasoner(catalog)
    # test mode: a minimal scripted reasoner — just proves the system runs.
    return FakeReasoner([
        AgentAction(thought="test mode: assembly smoke check, then conclude",
                    kind=ActionKind.CONCLUDE,
                    conclusion="assembly smoke test — the full pipeline ran end-to-end "
                               "(use --mode live for a real investigation)"),
    ])


# ---- readable report of the result ------------------------------------------

def print_result(res, verbose: bool = False) -> None:
    line = "=" * 72
    print("\n" + line)
    print("INVESTIGATION RESULT")
    print(line)
    print(f"status     : {res.status}")
    print(f"reason     : {res.reason}")
    print(f"steps used : {res.steps_used}")
    print(f"audit recs : {len(res.audit)}  (full-raw evidence preserved, hash-stamped)")

    print("\nHYPOTHESES:")
    hyps = res.memory.all_hypotheses()
    for h in hyps:
        print(f"  {h.hyp_id} [{h.status.value}]: {h.statement}")
    if not hyps:
        print("  (none)")

    print("\nGROUNDED FINDINGS:")
    findings = res.memory.findings_list()
    for f in findings:
        print(f"  {f.finding_id}: {f.statement}   [evidence: {', '.join(f.evidence_ids)}]")
    if not findings:
        print("  (none)")

    print("\nSUSPICIOUS ABSENCES (W1):")
    absences = res.memory.negative_indicators()
    for n in absences:
        print(f"  {n.neg_id}: {n.looked_for}  (suspicious={n.suspicious})")
    if not absences:
        print("  (none)")

    print("\nCONCLUSION:")
    print(f"  {res.reason}")

    if verbose:
        print("\n" + "-" * 72)
        print("FULL INVESTIGATION LOG (every step, in order)")
        print("-" * 72)
        for e in res.memory.full_log():
            print(f"  [step {e.step:>2} | {e.kind:<10}] {e.text}")

    print(line + "\n")


# ---- entry point -------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run one anti-forensic investigation on a capture folder.")
    parser.add_argument("--case", required=True, help="path to ONE preserved capture folder")
    parser.add_argument("--mode", choices=["test", "live"], default="test",
                        help="test = fake reasoner (no GPU); live = real LLM on the VM")
    parser.add_argument("--max-steps", type=int, default=12, help="investigation step budget")
    parser.add_argument("--verbose", action="store_true",
                        help="print the full step-by-step investigation log (for diagnosing a run)")
    args = parser.parse_args()

    print(f"Mode        : {args.mode}")
    print(f"Capture     : {args.case}")
    if args.mode == "live":
        print(f"Model       : {os.getenv('OLLAMA_MODEL', 'qwen2.5:7b-instruct')} "
              f"@ {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")

    # assemble the pieces
    catalog = build_catalog()
    knowledge_base = build_knowledge_base()
    memory = CaseMemory()
    dual = DualOutput()

    # box 3 (lite): what artifacts are actually here?
    inventory = scan_capture(args.case)
    print("\nArtifact inventory (primary artifacts given to the agent):")
    print(format_inventory(inventory))
    print("\nExcluded from the agent's input (not device-produced):")
    print(format_excluded(inventory))

    initial_observation = (
        "You are investigating ONE preserved Android capture for possible anti-forensic "
        "activity. Examine the artifacts listed below using the forensic tools. Call tools "
        "with these EXACT paths; do NOT invent paths.\n\n"
        "Available artifacts:\n" + format_inventory(inventory)
    )

    reasoner = build_reasoner(args.mode, catalog)
    loop = BoundedInvestigationLoop(reasoner, catalog, max_steps=args.max_steps,
                                    memory=memory, dual=dual, knowledge_base=knowledge_base,
                                    progress=True)
    result = loop.run(initial_observation=initial_observation)
    print_result(result, verbose=args.verbose)


if __name__ == "__main__":
    main()