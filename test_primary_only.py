"""
Test — the agent receives only PRIMARY artifacts (device-produced), never
analyst-derived extracts.

The real capture held 02_logcat_hits_afterwipe.txt: lines COPIED out of the full
logcat dump by a Windows search tool, each prefixed with
"C:\\...\\01_logcat_full_dump_afterwipe.txt:150:". Giving that to the agent risks
(1) false corroboration (one source counted twice) and (2) leaking what an analyst
already chose to search for.

Proves, with NO LLM:
  1. a Windows search-tool export (UTF-16, "<file>:<line>:" prefix) is excluded,
     with a stated reason — detected by CONTENT, not by its file name;
  2. a "grep -n" style export ("<line>:" prefix) is excluded too;
  3. the real full dump stays in — even when its NAME contains "hits";
  4. the agent's inventory block lists only primary files; the excluded list
     (shown to the human) names the extract and why.
"""
import tempfile
from pathlib import Path
import main as m

LOG = "05-13 10:28:16.904  2022  2086 W PackageParser: Unknown element under <manifest>"
PREFIX = r"C:\AndroidForensicsProject\CleanerScope\captures\X\PhaseB\01_logcat_full_dump_afterwipe.txt"

with tempfile.TemporaryDirectory() as d:
    lc = Path(d) / "PhaseB_PostClean_Logcat"
    lc.mkdir()
    # primary full dump (UTF-16 like the real ones)
    (lc / "01_logcat_full_dump_afterwipe.txt").write_bytes(
        b"\xff\xfe" + "\r\n".join([LOG] * 40).encode("utf-16-le"))
    # Windows search-tool export (the real 02 shape)
    (lc / "02_logcat_hits_afterwipe.txt").write_bytes(
        b"\xff\xfe" + "\r\n".join(f"{PREFIX}:{150 + k}:{LOG}" for k in range(27)).encode("utf-16-le"))
    # grep -n style export with an innocent-looking name
    (lc / "03_logcat_notes.txt").write_text("\n".join(f"{200 + k}:{LOG}" for k in range(10)), encoding="utf-8")
    # a PRIMARY dump whose name happens to contain "hits" -> must NOT be excluded
    (lc / "04_logcat_hits_device.txt").write_text("\n".join([LOG] * 10), encoding="utf-8")

    inv = m.scan_capture(d)
    by_name = {Path(i["path"]).name: i for i in inv}

    print("TEST 1 — Windows search-tool export excluded, with a reason")
    print("   ", by_name["02_logcat_hits_afterwipe.txt"].get("excluded"))
    assert "analyst-derived" in by_name["02_logcat_hits_afterwipe.txt"].get("excluded", "")
    print("  OK")

    print("TEST 2 — grep -n style export excluded")
    assert by_name["03_logcat_notes.txt"].get("excluded")
    print("  OK")

    print("TEST 3 — primary dumps kept (decided by content, not by name)")
    assert not by_name["01_logcat_full_dump_afterwipe.txt"].get("excluded")
    assert not by_name["04_logcat_hits_device.txt"].get("excluded")
    print("  OK")

    print("TEST 4 — agent sees only primary files; human sees what was excluded and why")
    agent_block = m.format_inventory(inv)
    human_block = m.format_excluded(inv)
    print(agent_block)
    assert "01_logcat_full_dump_afterwipe.txt" in agent_block and "04_logcat_hits_device.txt" in agent_block
    assert "02_logcat_hits_afterwipe.txt" not in agent_block and "03_logcat_notes.txt" not in agent_block
    assert "02_logcat_hits_afterwipe.txt" in human_block and "reason:" in human_block
    print("  OK")

print("\nALL PRIMARY-ARTIFACTS-ONLY TESTS PASSED")