"""
Test — BOX 5 evidence digest (2026-11-19): every artifact read IN FULL by
deterministic code before the agent reasons; generic cross-artifact links.

Uses a SYNTHETIC capture with made-up app names (pkg.alpha.cleaner, ...), so it
proves the logic is generic — nothing here knows any real app.

Proves, with NO LLM:
  1. every primary artifact is read through the allow-listed tools and preserved
     in the audit store (evidence ids), excluded files are not read;
  2. structured records in an app's store are decoded and summarised IN FULL
     (fields identical across all records, list sizes summed, time span);
  3. system-log lines about files are grouped by the process that wrote them, and
     the process is attributed to its app from the system's own "Start proc" line;
  4. cross-artifact links are computed: shared file names, app presence across
     artifact kinds, time windows in one format;
  5. the digest is pinned for the agent, its artifacts count as read, and quotes
     taken from it pass the verbatim checker -> a clearing ACH -> HIGH;
  6. the digest code contains no app names; main.py has a --no-digest ablation flag.
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
print(d.text)

print("\n1 — every primary artifact read in full and preserved; the extract is not read")
prim = {i["path"] for i in inv if not i.get("excluded")}
assert d.read_paths == prim and len(prim) == 4
assert not any("hits.txt" in p for p in d.read_paths)
assert len(dual.audit) >= 4
print("  OK")

print("2 — structured records decoded in full")
pr = d.facts["prefs"][0]
assert pr["records"] == 2 and pr["list_totals"] == {"items": 6}
assert "success=True (2/2)" in pr["uniform_fields"] and "errors=0 (2/2)" in pr["uniform_fields"]
assert pr["time_range"] == ("05-13 10:01:00", "05-13 10:02:30")
print("  OK")

print("3 — log lines about files attributed to their app via the system's own line")
lg0 = d.facts["logcat"][0]
assert lg0["pid"] == "777" and lg0["owner"] == PKG and lg0["count"] == 6
assert "Start proc 777:" + PKG in d.text
print("  OK")

print("4 — cross-artifact links")
shared = d.facts["links"]["shared_file_names"]
assert any(len(v) == 6 for v in shared.values()), shared
kinds = {w.split(" [")[0].split(" process")[0] for w in d.facts["links"]["app_presence"][PKG]}
assert {"app-private store", "usage timeline", "recent task", "system log"} <= kinds, kinds
assert "6 file name(s) appear in BOTH" in d.text and "time windows" in d.text
print("  OK")

print("5 — pinned for the agent; quotes from it verify; clearing ACH -> HIGH")
sid = lg0["start_evidence_id"]; pid_ev = lg0["evidence_id"]; prefs_ev = pr["evidence_id"]
def a(cat_, ev, q): return {"category": cat_, "disposition": "ruled_out", "rationale": "see digest",
                            "evidence_ids": [ev], "quote": q}
script = [json.dumps({"thought": "judge", "action": "analyze", "alt_check": {
    "claim": "a secure file-wiping operation was executed on this device", "assessments": [
        a("normal", prefs_ev, '"success": true'),
        a("another_app", sid, f"Start proc 777:{PKG}"),
        a("system", pid_ev, "System.out: Removing file:"),
        a("acquisition", d.evidence[-1][0], "errors=0 (2/2)")]}}),   # a DIGEST line, citing the digest id
    json.dumps({"thought": "done", "action": "conclude", "verdict": "detected",
                "category": "artifact_wiping", "evidence_ids": [prefs_ev, pid_ev, sid],
                "conclusion": "wipe executed"})]
class R:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s); self.prompts = []
    def invoke(self, p): self.prompts.append(p); return R(self.s.pop(0))
llm = FakeLLM(script)
loop = BoundedInvestigationLoop(LLMReasoner(cat, llm=llm), cat, max_steps=4, dual=dual)
res = loop.run(initial_observation="Investigate.\nAvailable artifacts:\n" + m.format_inventory(inv), digest=d)
first = llm.prompts[0]
assert "CASE DIGEST" in first and "all listed artifacts have been read" in first
print("  ", [e.text for e in res.memory.full_log() if e.kind == "ach"][0][:90])
assert res.verdict == "detected" and res.confidence == "high", (res.verdict, res.confidence)
print("  OK")

print("6 — generic code; ablation flag present")
src = open("engine/evidence_digest.py", encoding="utf-8").read().lower()
for name in ("androideraser", "cbinnovations", "shredder", "ccleaner", "dod5220"):
    assert name not in src, name
assert "--no-digest" in open("main.py", encoding="utf-8").read()
print("  OK")

print("\nALL DIGEST (BOX 5) TESTS PASSED")