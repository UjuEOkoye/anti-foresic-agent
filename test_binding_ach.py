"""
Test — Fix 3: the ACH gate is BINDING and the verdict is structured.

Live run #3 (2026-11-17): every ACH on the main claim was BLOCKED, yet the model
concluded "high confidence ... no plausible alternative explanations remain".
The model's prose set the verdict and the confidence; the gate was only advisory.

Proves, with NO LLM (real LLMReasoner + real loop, scripted model replies):
  1. REPLAY OF RUN #3: ACH blocked, then "detected" -> REFUSED; the agent is told
     why; if it never fixes it, the run ends INCONCLUSIVE (never "detected").
  2. "detected" with NO alt_check at all -> REFUSED.
  3. after a blocked ACH, the agent re-checks with evidence, it CLEARS, then
     "detected" is accepted — and the confidence comes from the GATE ("reduced"),
     NOT from the model, even though the model's prose claims "high".
  4. "detected" with an invented evidence id or an unknown category -> REFUSED.
  5. "inconclusive" / "not_detected" need no ACH; a missing verdict is recorded
     conservatively as "inconclusive" (prose cannot turn it into a detection).
"""
import json
from engine.llm_reasoner import LLMReasoner
from engine.bounded_loop import BoundedInvestigationLoop
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType

TOOL = ToolSchema(name="read_sharedprefs", purpose="Read shared_prefs.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("entries", FieldType.OBJECT, "kv")],
                  handler=lambda artifact_path: {"status": "ok", "entries": {"method": "3-pass overwrite"}})
def cat():
    c = ToolCatalog(); c.register(TOOL); return c

class R:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s)
    def invoke(self, p):
        return R(self.s.pop(0) if self.s else
                 '{"thought":"still sure","action":"conclude","verdict":"detected",'
                 '"category":"artifact_wiping","evidence_ids":["E0001"],"conclusion":"high confidence"}')

READ = '{"thought":"read","action":"call_tool","tool_name":"read_sharedprefs","tool_args":{"artifact_path":"/p.xml"}}'
CLAIM = "a secure file-wiping operation was executed on this device"

def ach(dispositions):
    cats = ["normal", "another_app", "system", "acquisition"]
    return json.dumps({"thought": "check main claim", "action": "analyze", "alt_check": {
        "claim": CLAIM, "assessments": [
            {"category": c, "disposition": d, "rationale": "r", "evidence_ids": ["E0001"]}
            for c, d in zip(cats, dispositions)]}})

def conclude(verdict="detected", category="artifact_wiping", ids=("E0001",), prose="high confidence, nothing else possible"):
    d = {"thought": "conclude", "action": "conclude", "conclusion": prose}
    if verdict is not None:
        d.update(verdict=verdict, category=category, evidence_ids=list(ids))
    return json.dumps(d)

def run(script, steps=6):
    c = cat()
    return BoundedInvestigationLoop(LLMReasoner(c, llm=FakeLLM(script)), c, max_steps=steps).run()

def refusals(res):
    return [e.text for e in res.memory.full_log() if "CONCLUSION REFUSED" in e.text]


print("TEST 1 — replay of run #3: ACH BLOCKED, model says 'detected, high confidence'")
res = run([READ, ach(["ruled_out", "ruled_out", "plausible", "ruled_out"]), conclude()], steps=5)
print("  status:", res.status, "| verdict:", res.verdict, "| refusals:", len(refusals(res)))
print("  first refusal:", refusals(res)[0][:120], "...")
assert refusals(res) and "BLOCKED" in refusals(res)[0]
assert res.verdict == "inconclusive" and res.status == "inconclusive"
print("  OK — the model can no longer write a detection over a blocked gate")

print("TEST 2 — 'detected' with no alt_check at all -> refused")
res = run([READ, conclude()], steps=3)
assert refusals(res) and "no alt_check" in refusals(res)[0]
assert res.verdict == "inconclusive"
print("  OK")

print("TEST 3 — blocked, then re-checked with evidence -> clears; confidence from the GATE")
res = run([READ,
           ach(["ruled_out", "ruled_out", "plausible", "ruled_out"]),        # blocked
           ach(["ruled_out", "ruled_out", "ruled_out", "cannot_exclude"]),   # clears, reduced
           conclude(prose="HIGH confidence")])
print("  status:", res.status, "| verdict:", res.verdict, "| confidence:", res.confidence)
print("  reason:", res.reason)
assert res.status == "concluded" and res.verdict == "detected"
assert res.category == "artifact_wiping" and res.evidence_ids == ["E0001"]
assert res.confidence == "reduced"            # the model said HIGH; the gate says reduced
assert "reduced" in res.reason.lower() and res.explanation == "HIGH confidence"
print("  OK")

print("TEST 4 — invented evidence id / unknown category -> refused")
res = run([READ, ach(["ruled_out"] * 4), conclude(ids=("E0099",))], steps=4)
assert refusals(res) and "E0099" in refusals(res)[0]
res = run([READ, ach(["ruled_out"] * 4), conclude(category="magic")], steps=4)
assert refusals(res) and "category" in refusals(res)[0]
print("  OK")

print("TEST 4b — 'unclassified' is a valid category (pipeline box 7: Unknown/Unclassified)")
res = run([READ, ach(["ruled_out"] * 4), conclude(category="unclassified")], steps=4)
assert res.verdict == "detected" and res.category == "unclassified" and not refusals(res)
print("  OK")

print("TEST 5 — inconclusive / not_detected need no ACH; missing verdict -> inconclusive")
res = run([READ, conclude(verdict="inconclusive", ids=())])
assert res.status == "concluded" and res.verdict == "inconclusive" and not refusals(res)
res = run([READ, conclude(verdict="not_detected", ids=())])
assert res.verdict == "not_detected"
res = run([READ, conclude(verdict=None, prose="definitely a wipe, high confidence")])
assert res.verdict == "inconclusive" and res.confidence == "n/a"
print("  OK")

print("\nALL FIX-3 (BINDING ACH + STRUCTURED VERDICT) TESTS PASSED")