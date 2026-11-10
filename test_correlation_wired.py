"""
Test B2a — box 6.6 (correlation) wired into the loop via the ANALYZE move.

Proves, with NO LLM:
  PART 1: an ANALYZE step with observations from two evidence ids that AGREE
          produces a CORROBORATION; an expected-but-missing artifact produces a
          SUSPICIOUS ABSENCE ("missing != deleted").
  PART 2: the real LLMReasoner parses an "analyze" JSON into the right AgentAction.
"""
from engine.bounded_loop import (
    BoundedInvestigationLoop, FakeReasoner, AgentAction, ActionKind,
)
from engine.llm_reasoner import LLMReasoner, extract_first_json_object
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType


def _fake_read(artifact_path: str):
    return {"status": "ok", "artifact_path": artifact_path, "value": "x"}

TOOL = ToolSchema(
    name="read_sharedprefs", purpose="Read an Android shared_prefs XML.",
    args=[FieldSpec("artifact_path", FieldType.STRING, "path", required=True)],
    output=[FieldSpec("value", FieldType.STRING, "v")], handler=_fake_read,
)
def catalog():
    c = ToolCatalog(); c.register(TOOL); return c


print("PART 1 — ANALYZE step runs correlation (corroboration + absence)")
# steps 1-2: two tool calls -> evidence E0001, E0002
# step 3: ANALYZE — same fact (wiped_file=report.pdf) from BOTH ids -> corroboration;
#         expected usage_stats is NOT in present_locators -> suspicious absence
# step 4: conclude cleanly (no findings, so 6.8 passes)
script = [
    AgentAction(thought="pull shared_prefs", kind=ActionKind.CALL_TOOL,
                tool_name="read_sharedprefs", tool_args={"artifact_path": "/cap/sp.xml"}),
    AgentAction(thought="pull another source", kind=ActionKind.CALL_TOOL,
                tool_name="read_sharedprefs", tool_args={"artifact_path": "/cap/log.txt"}),
    AgentAction(
        thought="connect the dots", kind=ActionKind.ANALYZE,
        observations=[
            {"source_id": "E0001", "claim_key": "wiped_file", "value": "report.pdf"},
            {"source_id": "E0002", "claim_key": "wiped_file", "value": "report.pdf"},
        ],
        expected=[{"label": "usage_stats for the app", "locator": "/cap/usagestats",
                   "reason": "a launched app should leave a usage record"}],
        present_locators=["/cap/sp.xml", "/cap/log.txt"],   # usagestats NOT here
    ),
    AgentAction(thought="done", kind=ActionKind.CONCLUDE, conclusion="analysis complete"),
]
res = BoundedInvestigationLoop(FakeReasoner(script), catalog(), max_steps=8).run()

log_text = "\n".join(e.text for e in res.memory.full_log())
corr = [e.text for e in res.memory.full_log() if "CORROBORATED wiped_file=report.pdf" in e.text]
absences = res.memory.negative_indicators()
print("  status      :", res.status)
print("  corroboration:", corr)
print("  absences     :", [(n.neg_id, n.looked_for, "suspicious="+str(n.suspicious)) for n in absences])
assert corr, "expected a corroboration across E0001+E0002"
assert any(n.suspicious and "usage_stats" in n.looked_for for n in absences), "expected a suspicious absence"
print("  PART 1 PASS\n")


print("PART 2 — LLMReasoner parses an 'analyze' JSON correctly")
j = ('{"thought":"connect","action":"analyze",'
     '"observations":[{"source_id":"E0001","claim_key":"wiped_file","value":"a.pdf","junk":"x"}],'
     '"expected":[{"label":"usage_stats","locator":"/u","reason":"r"}],'
     '"present_locators":["/a","/b"]}')
r = LLMReasoner(catalog(), llm=object())   # llm never called (we map directly)
a = r._action_from_doc(extract_first_json_object(j))
print("  kind      :", a.kind.value)
print("  observations:", a.observations)
print("  expected    :", a.expected)
print("  present     :", a.present_locators)
assert a.kind == ActionKind.ANALYZE
assert a.observations == [{"source_id": "E0001", "claim_key": "wiped_file", "value": "a.pdf"}]  # junk dropped
assert a.expected == [{"label": "usage_stats", "locator": "/u", "reason": "r"}]
assert a.present_locators == ["/a", "/b"]
print("  PART 2 PASS\n")

print("ALL B2a TESTS PASSED — box 6.6 correlation is wired via the ANALYZE move.")