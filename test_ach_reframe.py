"""
Test — Fix 1: the ACH check asks about EXECUTION, not INTENT.

Live run #1 (2026-11-17): the model blocked a well-evidenced wipe because "a
person might wipe for normal privacy reasons" (a motive question), and ran its
checks on side-claims instead of the main claim -> verdict "inconclusive".

Proves, with NO LLM:
  1. every one of the four alternatives has a defined question, and each asks
     whether the EVIDENCE could exist without the technique being executed;
  2. the reasoner's prompt now carries: execution-not-intent, ACH on the MAIN
     claim, and the four questions (single source of truth = ach.py);
  3. the deterministic gate in ach.py is UNCHANGED (still blocks on plausible,
     reduces on cannot_exclude, high when all ruled out);
  4. end-to-end through the real reasoner + loop: an execution claim whose four
     alternatives are ruled out is logged as HIGH confidence.
"""
from engine.ach import (
    ALT_CATEGORY_QUESTIONS, REQUIRED_CATEGORIES, AltCategory, AltAssessment,
    Disposition, run_ach,
)
from engine.llm_reasoner import LLMReasoner
from engine.bounded_loop import BoundedInvestigationLoop
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType


print("TEST 1 — four alternative questions, all about the evidence")
assert set(ALT_CATEGORY_QUESTIONS) == set(REQUIRED_CATEGORIES)
for cat, q in ALT_CATEGORY_QUESTIONS.items():
    assert len(q) > 40, cat
assert "WITHOUT the technique" in ALT_CATEGORY_QUESTIONS[AltCategory.NORMAL]
print("  OK")


TOOL = ToolSchema(name="read_sharedprefs", purpose="Read shared_prefs.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("entries", FieldType.OBJECT, "kv")],
                  handler=lambda artifact_path: {"status": "ok", "entries": {"method": "overwrite_3_pass"}})
cat = ToolCatalog(); cat.register(TOOL)

print("TEST 2 — prompt carries execution-not-intent + main-claim rule + the questions")
prompt = LLMReasoner(cat, llm=object())._system_prompt()
assert "NOT why" in prompt and "OUT OF SCOPE" in prompt
assert "MAIN claim" in prompt
assert "Do not conclude \"inconclusive\" when the main claim" in prompt
for q in ALT_CATEGORY_QUESTIONS.values():
    assert q in prompt, q[:40]
print("  OK")

print("TEST 3 — the deterministic gate is unchanged")
def A(c, d): return AltAssessment(category=c, disposition=d, rationale="r", evidence_ids=["E0001"])
allout = [A(c, Disposition.RULED_OUT) for c in REQUIRED_CATEGORIES]
assert run_ach("x", allout).confidence == "high"
one_plaus = allout[:-1] + [A(AltCategory.ACQUISITION_LIMIT, Disposition.PLAUSIBLE)]
assert run_ach("x", one_plaus).confidence == "blocked"
one_cx = allout[:-1] + [A(AltCategory.ACQUISITION_LIMIT, Disposition.CANNOT_EXCLUDE)]
assert run_ach("x", one_cx).confidence == "reduced"
print("  OK")

print("TEST 4 — real reasoner + loop: execution claim, all ruled out -> HIGH")
class R:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s)
    def invoke(self, p): return R(self.s.pop(0) if self.s else '{"action":"conclude","conclusion":"done"}')
script = [
    '{"thought":"read prefs","action":"call_tool","tool_name":"read_sharedprefs","tool_args":{"artifact_path":"/p.xml"}}',
    '{"thought":"check main claim","action":"analyze","alt_check":{"claim":"a secure file-wiping operation was executed on this device",'
    '"assessments":['
    '{"category":"normal","disposition":"ruled_out","rationale":"report records a completed run","evidence_ids":["E0001"]},'
    '{"category":"another_app","disposition":"ruled_out","rationale":"record is in that app private storage","evidence_ids":["E0001"]},'
    '{"category":"system","disposition":"ruled_out","rationale":"OS does not write overwrite reports","evidence_ids":["E0001"]},'
    '{"category":"acquisition","disposition":"ruled_out","rationale":"file parsed cleanly","evidence_ids":["E0001"]}]}}',
    '{"thought":"done","action":"conclude","conclusion":"artifact wiping detected (high confidence)"}',
]
res = BoundedInvestigationLoop(LLMReasoner(cat, llm=FakeLLM(script)), cat, max_steps=6).run()
ach_lines = [e.text for e in res.memory.full_log() if e.kind == "ach"]
print("  ", ach_lines)
assert ach_lines and "HIGH" in ach_lines[0] and "executed" in ach_lines[0]
assert res.status == "concluded"
print("  OK")

print("\nALL FIX-1 (ACH REFRAME) TESTS PASSED")