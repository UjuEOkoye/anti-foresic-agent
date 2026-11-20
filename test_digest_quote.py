"""
Test — PROVENANCE-AWARE QUOTE CHECK (2026-11-19, after digest runs 1-3).

Live runs 1-3 passed the finish line but stayed REDUCED: the agent quoted CASE DIGEST
lines (e.g. "errors=0 (4/4)") and cited the SOURCE records those lines were computed
from, not the digest id. Text like "(4/4)" exists only in the digest, so the quote
was rejected. Rule now: a quote is accepted if it appears word-for-word in ONE digest
line AND every evidence id that line was built from is among the cited ids.

Proves, with NO LLM (same synthetic capture as test_digest.py, made-up app names):
  1. digest-line quotes citing their own sources are ACCEPTED (per-artifact line,
     indented sub-line, cross-artifact link line citing both sources);
  2. the same quote citing UNRELATED evidence is REJECTED;
  3. a made-up quote is REJECTED even when the right sources are cited;
  4. a cross-link quote citing only ONE of its two sources is REJECTED;
  5. end to end: the live-run pattern (digest quotes + source ids) now clears -> HIGH,
     and the audit log says which digest line matched.
"""
import json, os, tempfile
from pathlib import Path
import main as m
from tools.registry import build_catalog
from engine.dual_output import DualOutput
from engine.evidence_digest import build_digest
from engine.llm_reasoner import LLMReasoner
from engine.bounded_loop import BoundedInvestigationLoop

PKG = "pkg.alpha.cleaner"
FILES = [f"photo {i}.jpg" for i in range(5)] + ["notes.pdf"]
root = Path(tempfile.mkdtemp())
# app-private store with TWO records joined by a separator
rec = lambda i, names: json.dumps({"id": f"R{i}", "startTime": f"2026.05.13 10:0{i}:00",
    "endTime": f"2026.05.13 10:0{i}:30", "success": True, "errors": 0,
    "method": {"passes": 3, "name": "MULTI_PASS"},
    "items": [{"name": n, "ok": True} for n in names]})
value = rec(1, FILES[:3]) + "\u201a\u2017\u201a" + rec(2, FILES[3:])
sp = root / "acq" / "data" / "data" / PKG / "shared_prefs"; sp.mkdir(parents=True)
(sp / f"{PKG}.xml").write_text('<?xml version="1.0" encoding="utf-8"?><map><string name="reports">'
                               + value.replace("&", "&amp;").replace("<", "&lt;") + "</string></map>",
                               encoding="utf-8")
# usage timeline
us = root / "acq" / "data" / "system" / "usagestats" / "0" / "daily"; us.mkdir(parents=True)
(us / "1778720368768").write_text(
    '<?xml version="1.0" encoding="utf-8"?><usagestats version="1" endTime="100"><packages>'
    f'<package lastTimeActive="90" package="{PKG}" timeActive="5000" lastEvent="2" appLaunchCount="2" />'
    '<package lastTimeActive="50" package="pkg.beta.launcher" timeActive="900" lastEvent="1" appLaunchCount="1" />'
    '</packages><event-log>'
    f'<event time="10" package="{PKG}" class="{PKG}.Main" type="1" />'
    f'<event time="20" package="{PKG}" class="{PKG}.FilePicker" type="1" />'
    '</event-log></usagestats>', encoding="utf-8")
# recent task
rt = root / "acq" / "data" / "system_ce" / "0" / "recent_tasks"; rt.mkdir(parents=True)
(rt / "4_task.xml").write_text(f'<?xml version="1.0" encoding="utf-8"?><task task_id="4" '
                               f'real_activity="{PKG}/.Main" calling_package="{PKG}" effective_uid="10042" />',
                               encoding="utf-8")
# system log (UTF-16 like real Windows dumps) + an analyst "hits" extract that must be excluded
lg = root / "acq" / "logcat"; lg.mkdir(parents=True)
log = [f"05-13 09:59:50.000  2000  2010 I ActivityManager: Start proc 777:{PKG}/u0a42 for activity {PKG}/.Main",
       "05-13 09:59:51.000  2000  2010 I ActivityManager: Start proc 888:pkg.beta.launcher/u0a10 for activity x"]
log += [f"05-13 10:0{1 + (i > 2)}:1{i}.000   777   780 I System.out: Removing file: /storage/emulated/0/DCIM/{f}"
        for i, f in enumerate(FILES)]
log += ["05-13 10:05:00.000   888   888 W Launcher: cannot open /data/user/0/pkg.beta.launcher/cache/x.tmp"] * 2
log += ["05-13 10:06:00.000  2000  2010 I chatty: routine line"] * 50
(lg / "logcat.txt").write_bytes(b"\xff\xfe" + "\r\n".join(log).encode("utf-16-le"))
(lg / "hits.txt").write_text("\n".join(f"C:\\x\\logcat.txt:{i}:{l}" for i, l in enumerate(log[:20])))

inv = m.scan_capture(str(root))
cat = build_catalog()
dual = DualOutput()
from tools.search_evidence import make_search_evidence_tool
cat.register(make_search_evidence_tool(dual.audit))
d = build_digest(inv, cat, dual)

pr = d.facts["prefs"][0]; lg0 = d.facts["logcat"][0]
prefs_ev, pid_ev, sid = pr["evidence_id"], lg0["evidence_id"], lg0["start_evidence_id"]
other_ev = d.facts["logcat"][1]["evidence_id"]          # the launcher's log group
loop = BoundedInvestigationLoop(LLMReasoner(cat, llm=None), cat, max_steps=4, dual=dual)
loop._index_digest(d.text)
ok = loop._appears_verbatim

print("1 — digest-line quotes citing their own sources are accepted")
assert ok("errors=0 (2/2), method.name='MULTI_PASS' (2/2)", [prefs_ev])        # indented sub-line
assert ok("list sizes summed over records: items=6", [prefs_ev, pid_ev])          # extra ids are fine
assert ok("6 line(s) 'System.out: Removing file: <path>' written by PID 777", [pid_ev])
assert ok(f"PID 777 belongs to {PKG}", [sid])                                       # line with own id
assert ok("6 file name(s) appear in BOTH app-private record [E0001], system log (pid 777) [E0005]"
          .replace("E0001", prefs_ev).replace("E0005", pid_ev), [prefs_ev, pid_ev])
print("  OK")

print("2 — the same quote citing unrelated evidence is rejected")
assert not ok("errors=0 (2/2)", [other_ev])
assert not ok("written by PID 777", [other_ev])
print("  OK")

print("3 — a made-up quote is rejected even with the right sources")
assert not ok("errors=5 (2/2)", [prefs_ev])
assert not ok("method.passes=7 (2/2)", [prefs_ev, pid_ev])
print("  OK")

print("4 — a cross-link quote citing only one of its two sources is rejected")
assert not ok("6 file name(s) appear in BOTH", [prefs_ev])
assert not ok("6 file name(s) appear in BOTH", [pid_ev])
print("  OK")

print("5 — end to end: live-run pattern now clears -> HIGH")
def a(cat_, ev, q): return {"category": cat_, "disposition": "ruled_out", "rationale": "see digest",
                            "evidence_ids": ev, "quote": q}
script = [json.dumps({"thought": "judge", "action": "analyze", "alt_check": {
    "claim": "a secure file-wiping operation was executed on this device", "assessments": [
        a("normal", [prefs_ev, pid_ev], "method.passes=3 (2/2), success=True (2/2)"),
        a("another_app", [sid], f"Start proc 777:{PKG}"),
        a("system", [prefs_ev, pid_ev], "6 file name(s) appear in BOTH"),
        a("acquisition", [pid_ev], "Removing file: /storage/emulated/0/DCIM/photo 0.jpg")]}}),
    json.dumps({"thought": "done", "action": "conclude", "verdict": "detected",
                "category": "artifact_wiping", "evidence_ids": [prefs_ev, pid_ev, sid],
                "conclusion": "wipe executed"})]
class R:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s)
    def invoke(self, p): return R(self.s.pop(0))
loop2 = BoundedInvestigationLoop(LLMReasoner(cat, llm=FakeLLM(script)), cat, max_steps=4, dual=dual)
res = loop2.run(initial_observation="Investigate.\nAvailable artifacts:\n" + m.format_inventory(inv), digest=d)
log = [e.text for e in res.memory.full_log()]
assert not any("without a verbatim quote" in t for t in log), [t for t in log if "verbatim" in t]
assert any("quote matched a digest line computed from" in t for t in log)
assert res.verdict == "detected" and res.confidence == "high", (res.verdict, res.confidence)
print("  OK")

print("\nALL PROVENANCE-QUOTE TESTS PASSED")