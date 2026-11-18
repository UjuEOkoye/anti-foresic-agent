"""
Test — Fixes D and E (after live run #5, 2026-11-17).

Run #5:
  - correlation logged a FALSE CONFLICT: the agent described the same 9 files two
    ways ("... (9 files listed)" vs "Same 9 files cleared in logcat"), and the
    correlator compares values exactly (Fix D, part 1);
  - an alternative was "ruled out" with a reason that the cited evidence did not
    support (Fix D, part 2: reasons must quote their evidence word-for-word);
  - it recorded "usage_stats ... not found" at a Phase-B path whose file was in
    the inventory and had never been read (Fix E).

Proves, with NO LLM (real reasoner + real loop, scripted replies):
  D1. REPLAY: paraphrased observation values are IGNORED (logged), so no false
      conflict; the same facts copied verbatim (one file name each) CORROBORATE.
  D2. "ruled_out" whose quote is not word-for-word in the cited evidence counts as
      "cannot_exclude"; a verbatim quote is accepted. (Limit, documented: a real
      quote can still support a wrong conclusion — that is for the human reviewer.)
  E1. REPLAY: an absence at an inventory artifact that has NOT been read is
      REFUSED and not recorded; the agent is told to read it.
  E2. after the artifact IS read, an absence of content in it is allowed.
  E3. an "expected" artifact (correlation) that is in the inventory but unread is
      not turned into an absence.
"""
import json
from engine.llm_reasoner import LLMReasoner
from engine.bounded_loop import BoundedInvestigationLoop
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType

FILES = ["photo_01.jpg", "photo_02.jpg", "report.pdf"]
DATA = {
    "/cap/prefs.xml": {"status": "ok", "entries": {"savekey_reports":
        "mValue:DoD5220_22_ME, mCycles:3, reportDetail: " + ", ".join(FILES)}},
    "/cap/logcat.txt": {"status": "ok", "matches": [
        {"line": 10 + i, "text": f"I System.out: Clearing DocumentFile: /storage/emulated/0/Pictures/{f}"}
        for i, f in enumerate(FILES)]},
    "/cap/PhaseD/usage_stats/0/daily/1": {"status": "ok", "packages": [{"package": "pkg.a"}]},
    "/cap/PhaseB/usage_stats/0/daily/1": {"status": "ok", "packages": [{"package": "pkg.a"}]},
}
TOOL = ToolSchema(name="read_artifact", purpose="Read an artifact.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("status", FieldType.STRING, "s")],
                  handler=lambda artifact_path: dict(DATA[artifact_path], artifact_path=artifact_path))
def cat():
    c = ToolCatalog(); c.register(TOOL); return c

BRIEFING = ("Investigate.\nAvailable artifacts:\n"
            + "".join(f"    {p}\n" for p in DATA))

class R:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s)
    def invoke(self, p): return R(self.s.pop(0) if self.s else
                                  '{"thought":"done","action":"conclude","verdict":"inconclusive"}')

def read(p): return json.dumps({"thought": "read", "action": "call_tool", "tool_name": "read_artifact",
                                "tool_args": {"artifact_path": p}})
def analyze(**kw): return json.dumps(dict({"thought": "analyze", "action": "analyze"}, **kw))
def run(script, steps=8):
    c = cat()
    return BoundedInvestigationLoop(LLMReasoner(c, llm=FakeLLM(script)), c,
                                    max_steps=steps).run(initial_observation=BRIEFING)
def log(res, kind=None):
    return [e.text for e in res.memory.full_log() if kind is None or e.kind == kind]


print("D1 — replay of run #5: paraphrased values are ignored; verbatim values corroborate")
res = run([read("/cap/prefs.xml"), read("/cap/logcat.txt"),
           analyze(observations=[
               {"source_id": "E0001", "claim_key": "wiped_files", "value": "WhatsApp Image... (9 files listed)"},
               {"source_id": "E0002", "claim_key": "wiped_files", "value": "Same 9 files cleared in logcat"}])])
assert not any("CONFLICT" in t for t in log(res, "correlation")), "false conflict came back"
assert sum("OBSERVATION IGNORED" in t for t in log(res)) == 2
res = run([read("/cap/prefs.xml"), read("/cap/logcat.txt"),
           analyze(observations=[o for f in FILES for o in (
               {"source_id": "E0001", "claim_key": f"wiped:{f}", "value": f},
               {"source_id": "E0002", "claim_key": f"wiped:{f}", "value": f})])])
corr = [t for t in log(res, "correlation") if "CORROBORATED" in t]
print("  ", corr[0])
assert len(corr) == 3 and not any("CONFLICT" in t for t in log(res, "correlation"))
print("  OK")

print("D2 — 'ruled_out' needs a word-for-word quote from the cited evidence")
def ach(quote):
    cats = ["normal", "another_app", "system", "acquisition"]
    return analyze(alt_check={"claim": "a secure file-wiping operation was executed on this device",
        "assessments": [{"category": c, "disposition": "ruled_out", "rationale": "r",
                         "evidence_ids": ["E0001"], "quote": quote} for c in cats]})
res = run([read("/cap/prefs.xml"), ach("the app wiped everything securely")])    # invented quote
assert "REDUCED" in log(res, "ach")[0]
res = run([read("/cap/prefs.xml"), ach("mValue:DoD5220_22_ME, mCycles:3")])       # verbatim
assert "HIGH" in log(res, "ach")[0]
assert any('quote: "mValue:DoD5220_22_ME, mCycles:3"' in t for t in log(res, "ach_detail"))
print("  OK  (limit: a real quote can still back a wrong conclusion -> human review, box 12)")

print("E1 — replay of run #5: absence at an UNREAD inventory artifact is refused")
res = run([read("/cap/PhaseD/usage_stats/0/daily/1"),
           analyze(absence={"looked_for": "usage_stats for wipe execution timing",
                            "location": "/cap/PhaseB/usage_stats/...", "suspicious": True})])
refused = [t for t in log(res) if "ABSENCE REFUSED" in t]
print("  ", refused[0][:130], "...")
assert refused and not res.memory.negative_indicators()
print("  OK")

print("E2 — after reading it, an absence of content in that file is allowed")
res = run([read("/cap/PhaseD/usage_stats/0/daily/1"), read("/cap/PhaseB/usage_stats/0/daily/1"),
           analyze(absence={"looked_for": "a launch event for pkg.b",
                            "location": "/cap/PhaseB/usage_stats/0/daily/1", "suspicious": False})])
assert not any("ABSENCE REFUSED" in t for t in log(res)) and len(res.memory.negative_indicators()) == 1
print("  OK")

print("E3 — an 'expected' artifact that is in the inventory but unread is not called missing")
res = run([read("/cap/prefs.xml"),
           analyze(expected=[{"label": "usage timeline", "locator": "/cap/PhaseB/usage_stats/...",
                              "reason": "a launched app leaves a record"}],
                   present_locators=["/cap/prefs.xml"])])
assert not res.memory.negative_indicators()
assert any("EXPECTED-ARTIFACT CHECK SKIPPED" in t for t in log(res))
print("  OK")

print("\nALL FIX D/E TESTS PASSED")