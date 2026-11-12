"""
Smoke test for main.py — NO GPU, NO model.

PART 1: scan_capture() classifies files into shared_prefs / usage_stats / logcat.
PART 2: a test-mode run assembles every piece and completes end-to-end.
"""
import tempfile
from pathlib import Path

import main as m
from engine.bounded_loop import BoundedInvestigationLoop
from engine.case_memory import CaseMemory
from engine.dual_output import DualOutput
from tools.registry import build_catalog
from knowledge_base import build_knowledge_base


def make_capture(root: str) -> None:
    r = Path(root)
    (r / "shared_prefs").mkdir(parents=True)
    (r / "shared_prefs" / "prefs.xml").write_text("<map></map>", encoding="utf-8")
    (r / "usage_stats" / "0" / "daily").mkdir(parents=True)
    (r / "usage_stats" / "0" / "daily" / "1778720368768").write_text("<usagestats/>", encoding="utf-8")
    (r / "logcat_full_dump.txt").write_text("line1\nline2\n", encoding="utf-8")


print("PART 1 — scan_capture classifies artifacts by type")
with tempfile.TemporaryDirectory() as d:
    make_capture(d)
    inv = m.scan_capture(d)
    types = sorted({i["type"] for i in inv})
    print("  found types:", types, "| files:", len(inv))
    assert {"shared_prefs", "usage_stats", "logcat"} <= set(types)
    block = m.format_inventory(inv)
    assert "shared_prefs" in block and "usage_stats" in block and "logcat" in block
    print("  PART 1 PASS\n")

print("PART 2 — test-mode run assembles and concludes end-to-end")
with tempfile.TemporaryDirectory() as d:
    make_capture(d)
    inv = m.scan_capture(d)
    catalog = build_catalog()
    kb = build_knowledge_base()
    reasoner = m.build_reasoner("test", catalog)
    loop = BoundedInvestigationLoop(reasoner, catalog, memory=CaseMemory(),
                                    dual=DualOutput(), knowledge_base=kb)
    res = loop.run(initial_observation="Available artifacts:\n" + m.format_inventory(inv))
    print("  status:", res.status, "| reason:", res.reason[:50], "...")
    assert res.status == "concluded"
    print("  PART 2 PASS\n")

print("ALL MAIN SMOKE TESTS PASSED")