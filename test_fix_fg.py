"""
Test — Fixes F and G (after live run #6, 2026-11-17).

Run #6:
  - correlation logged "CONFLICT on wiped_files" from a SINGLE source: many file
    names under one key were treated as a disagreement (Fix F, bug in our code);
  - the wipe report's file list was past the 300-char cut of the agent's view, so
    the agent could not see or quote the names, and the strongest corroboration
    (same names in the report AND the system log) was lost (Fix G).

Proves, with NO LLM:
  F1. REPLAY: many values for one key from ONE source -> no conflict.
  F2. a REAL conflict (two sources, one value each, different) is still reported.
  F3. two sources listing file names under one key -> the shared names
      CORROBORATE; names only one side has are not a "conflict".
  G1. search_evidence finds text that lies BEYOND the 300-char cut of a long
      value, returns verbatim snippets with their field path; unknown id ->
      not_found; it is registered by main.py.
  G2. END-TO-END (real reasoner + loop + search_evidence): read the long report,
      search it, read the log, give verbatim names under one key -> corroborations
      across the report and the log, no conflicts, nothing ignored.
"""
import json
from engine.correlation import Observation, correlate
from engine.dual_output import DualOutput, project
from engine.llm_reasoner import LLMReasoner
from engine.bounded_loop import BoundedInvestigationLoop
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType
from tools.search_evidence import make_search_evidence_tool

O = Observation

print("F1 — replay of run #6: one source, many file names under one key -> no conflict")
_, conf = correlate([O("E0004", "wiped_files", f"photo_{i}.jpg") for i in range(9)])
assert conf == []
print("  OK")

print("F2 — a real disagreement between two sources is still a conflict")
_, conf = correlate([O("E0003", "device_timezone", "America/Chicago"),
                     O("E0004", "device_timezone", "America/New_York")])
assert len(conf) == 1 and conf[0].values_by_source == {"E0003": "America/Chicago",
                                                        "E0004": "America/New_York"}
print("  OK")

print("F3 — two sources listing files: shared names corroborate, no conflict")
obs = ([O("E0002", "wiped_file", f) for f in ("a.jpg", "b.jpg", "c.pdf")] +
       [O("E0004", "wiped_file", f) for f in ("a.jpg", "b.jpg")])
corr, conf = correlate(obs)
assert sorted(c.value for c in corr) == ["a.jpg", "b.jpg"] and conf == []
print("  OK")

print("G1 — search_evidence reaches text beyond the 300-char cut")
names = [f"WhatsApp Image 2026-05-11 at 16.16.{i:02d}.jpeg" for i in range(9)]
report = ('{"mValue":"DoD5220_22_ME","mCycles":3,"padding":"' + "x" * 400 + '",'
          '"reportDetail":[' + ",".join('{"name":"%s","state":"done"}' % n for n in names) + "]}")
dual = DualOutput()
ev = dual.handle("read_sharedprefs", {"status": "ok", "entries": {"savekey_reports": report}})
eid = ev["evidence"]["evidence_id"]
view = json.dumps(project({"entries": {"savekey_reports": report}}))
assert names[5] not in view, "test setup: the name must be past the cut"
tool = make_search_evidence_tool(dual.audit)
r = tool.handler(evidence_id=eid, pattern="WhatsApp Image")
print("  ", r["note"], "| first hit field:", r["hits"][0]["field"])
assert r["match_count"] == 9 and any(names[5] in h["snippet"] for h in r["hits"])
assert all(h["snippet"] in report for h in r["hits"])          # verbatim
assert tool.handler(evidence_id="E9999", pattern="x")["status"] == "not_found"
assert "make_search_evidence_tool(dual.audit)" in open("main.py", encoding="utf-8").read()
print("  OK")

print("G2 — end-to-end: search the long report, then corroborate with the log")
LOG = {"status": "ok", "matches": [{"line": 100 + i, "text": "I System.out: Clearing DocumentFile: "
       f"/storage/emulated/0/DCIM/Camera/{n}"} for i, n in enumerate(names)]}
DATA = {"/cap/prefs.xml": {"status": "ok", "entries": {"savekey_reports": report}},
        "/cap/log.txt": LOG}
READ = ToolSchema(name="read_artifact", purpose="Read an artifact.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("status", FieldType.STRING, "s")],
                  handler=lambda artifact_path: dict(DATA[artifact_path], artifact_path=artifact_path))
dual = DualOutput()
cat = ToolCatalog(); cat.register(READ); cat.register(make_search_evidence_tool(dual.audit))

class R:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s)
    def invoke(self, p): return R(self.s.pop(0) if self.s else
                                  '{"thought":"done","action":"conclude","verdict":"inconclusive"}')
def j(**kw): return json.dumps(kw)
script = [
    j(thought="read report", action="call_tool", tool_name="read_artifact",
      tool_args={"artifact_path": "/cap/prefs.xml"}),
    j(thought="names are cut off; search", action="call_tool", tool_name="search_evidence",
      tool_args={"evidence_id": "E0001", "pattern": "WhatsApp Image"}),
    j(thought="read log", action="call_tool", tool_name="read_artifact",
      tool_args={"artifact_path": "/cap/log.txt"}),
    j(thought="correlate", action="analyze", observations=(
        [{"source_id": "E0001", "claim_key": "wiped_file", "value": n} for n in names] +
        [{"source_id": "E0003", "claim_key": "wiped_file", "value": n} for n in names])),
]
res = BoundedInvestigationLoop(LLMReasoner(cat, llm=FakeLLM(script)), cat, max_steps=6,
                               dual=dual).run()
logs = [e.text for e in res.memory.full_log()]
corr = [t for t in logs if t.startswith("CORROBORATED")]
print("  ", corr[0])
assert len(corr) == 9
assert not any("CONFLICT" in t for t in logs) and not any("OBSERVATION IGNORED" in t for t in logs)
print("  OK")

print("\nALL FIX F/G TESTS PASSED")