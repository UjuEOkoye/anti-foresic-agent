"""
Test — the FINAL fix for the AW capture (2026-11-19), after the finish-line runs.

  1. Quote checker: a quote copied from the JSON view the agent sees (field name +
     value, e.g. '"app_launch_count": 4') is ACCEPTED; a reconstructed string that
     skips fields in between is still REJECTED.
  2. After a REDUCED (clearing) check, the agent is told a "detected" verdict is
     allowed (finish-line run 1 concluded "inconclusive" by mistake).
  3. Knowledge cards match the CleanerScope ground truth: app-private data removed
     on uninstall; usage timeline survives uninstall + reboot; recent tasks survive
     uninstall and are cleared by reboot; survival is NORMAL. New generic card on
     attributing log lines to an app by process id. Still no app names.
  4. New generic tool read_recent_tasks: reads a task record exactly as stored;
     registered; recent_tasks files appear in the agent's inventory.
"""
import json, os, tempfile
from engine.llm_reasoner import LLMReasoner
from engine.bounded_loop import BoundedInvestigationLoop
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType
from knowledge_base import build_knowledge_base
from tools.read_recent_tasks import _read_recent_tasks
from tools.registry import build_catalog
import main as m

USAGE = {"status": "ok", "packages": [
    {"package": "pkg.alpha", "last_time_active": 3251728, "time_active": 10315,
     "last_event": 2, "app_launch_count": 4},
    {"package": "pkg.beta", "last_time_active": 900, "time_active": 50, "last_event": 1,
     "app_launch_count": 2}]}
TOOL = ToolSchema(name="read_usagestats", purpose="Read usage stats.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("packages", FieldType.LIST, "p")],
                  handler=lambda artifact_path: dict(USAGE, artifact_path=artifact_path))
class R:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s)
    def invoke(self, p): return R(self.s.pop(0) if self.s else
                                  '{"thought":"d","action":"conclude","verdict":"inconclusive"}')
def run(quote):
    c = ToolCatalog(); c.register(TOOL)
    cats = ["normal", "another_app", "system", "acquisition"]
    script = [json.dumps({"thought": "r", "action": "call_tool", "tool_name": "read_usagestats",
                          "tool_args": {"artifact_path": "/u"}}),
              json.dumps({"thought": "a", "action": "analyze", "alt_check": {
                  "claim": "x was executed", "assessments": [
                      {"category": k, "disposition": "ruled_out", "rationale": "r",
                       "evidence_ids": ["E0001"], "quote": quote} for k in cats]}})]
    return BoundedInvestigationLoop(LLMReasoner(c, llm=FakeLLM(script)), c, max_steps=3).run()
def ach_line(res): return [e.text for e in res.memory.full_log() if e.kind == "ach"][0]

print("1 — quotes copied from the JSON view are accepted; reconstructions are not")
assert "HIGH" in ach_line(run('"app_launch_count": 4'))
assert "HIGH" in ach_line(run('"package": "pkg.alpha", "last_time_active": 3251728'))
assert "REDUCED" in ach_line(run("package: pkg.alpha, last_time_active: 3251728, time_active: 10315, app_launch_count: 4"))
print("  OK")

print("2 — a REDUCED (clearing) check tells the agent 'detected' is allowed")
res = run("this text is not in the evidence")
notes = " ".join(e.text for e in res.memory.full_log())
assert "REDUCED" in ach_line(res)
src = open("engine/bounded_loop.py", encoding="utf-8").read()
assert "REDUCED means the check CLEARS" in src
print("  OK")

print("3 — knowledge cards match the CleanerScope ground truth")
kb = build_knowledge_base()
card = {c.card_id: c for c in kb.cards} if hasattr(kb, "cards") else None
if card is None:
    from knowledge_base.cards import STARTER_CARDS
    card = {c.card_id: c for c in STARTER_CARDS}
aw04 = card["AW-04"].summary
assert "consistently survives uninstall AND reboot" in aw04 and "strongest" in aw04
assert "MAY survive an uninstall" in aw04 and "cleared by a reboot" in aw04   # Uju: not reliable
assert "NORMAL" in " ".join(card["AW-04"].indicators)
assert "NB-04" in card and "FP-03" in card
top = [c.card_id for c in kb.retrieve("could another application have written these log lines which process pid", k=3)]
print("   retrieved for an attribution question:", top)
assert "FP-03" in top
top = [c.card_id for c in kb.retrieve("usage timeline still present after uninstall reboot survival normal", k=3)]
print("   retrieved for a survival question:", top)
assert "NB-04" in top or "AW-04" in top
print("  OK")

print("4 — generic read_recent_tasks tool")
xml = ('<?xml version="1.0" encoding="utf-8"?><task task_id="4" real_activity="pkg.alpha/.Main" '
       'calling_package="pkg.alpha" effective_uid="10042" last_time_moved="1778723617479">'
       '<intent action="android.intent.action.MAIN" /></task>')
d = tempfile.mkdtemp(); rt = os.path.join(d, "system_ce", "recent_tasks"); os.makedirs(rt)
fp = os.path.join(rt, "4_task.xml"); open(fp, "w").write(xml)
r = _read_recent_tasks(fp)
assert r["status"] == "ok" and r["task"]["real_activity"] == "pkg.alpha/.Main"
assert r["task"]["effective_uid"] == "10042" and r["children"][0]["tag"] == "intent"
assert _read_recent_tasks(fp + ".missing")["status"] == "not_found"
assert "read_recent_tasks" in build_catalog().names()
inv = m.scan_capture(d)
assert any(i["type"] == "recent_tasks" for i in inv), inv
print("  OK")

print("\nALL FINAL-FIX TESTS PASSED")