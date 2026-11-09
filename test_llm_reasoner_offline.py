"""
Offline test of LLMReasoner — NO Ollama, NO GPU.
Injects a FAKE model that returns canned text, to prove: (1) JSON extraction is
robust, (2) JSON -> AgentAction mapping is correct, (3) the real reasoner drives
the real bounded loop end-to-end and grounds findings to real evidence ids.
"""
from engine.llm_reasoner import LLMReasoner, extract_first_json_object
from engine.bounded_loop import BoundedInvestigationLoop, ActionKind
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType


class FakeReply:
    def __init__(self, content): self.content = content

class FakeLLM:
    def __init__(self, scripted): self._s = list(scripted); self._i = 0
    def invoke(self, prompt):
        out = self._s[self._i] if self._i < len(self._s) else '{"action":"conclude","conclusion":"done"}'
        self._i += 1
        return FakeReply(out)


def _fake_read(artifact_path: str):
    return {"status": "ok", "artifact_path": artifact_path,
            "packages": [{"package": "com.example.x", "appLaunchCount": 4}]}

FAKE_TOOL = ToolSchema(
    name="read_usagestats",
    purpose="Read an Android usage_stats XML timeline.",
    args=[FieldSpec("artifact_path", FieldType.STRING, "path to the file", required=True)],
    output=[FieldSpec("packages", FieldType.LIST, "per-package counters")],
    handler=_fake_read,
)

def build_catalog():
    c = ToolCatalog(); c.register(FAKE_TOOL); return c


print("TEST 1 — JSON extraction survives prose + ``` fences")
messy = 'Sure!\n```json\n{"action":"conclude","conclusion":"x"}\n```\nDone.'
assert extract_first_json_object(messy) == {"action": "conclude", "conclusion": "x"}
print("  OK")

print("TEST 2 — call_tool JSON maps to AgentAction (junk absence key dropped)")
r = LLMReasoner(build_catalog(), llm=FakeLLM(['{}']))
j = ('{"thought":"check timeline","action":"call_tool","tool_name":"read_usagestats",'
     '"tool_args":{"artifact_path":"/x"},"keep_fields":["packages"],'
     '"propose_hypothesis":"a deletion tool may have run",'
     '"absence":{"looked_for":"shared_prefs","location":"/data","suspicious":true,"note":"gone","junk":"x"}}')
a = r._action_from_doc(extract_first_json_object(j))
assert a.kind == ActionKind.CALL_TOOL and a.tool_name == "read_usagestats"
assert a.tool_args == {"artifact_path": "/x"} and a.keep_fields == ["packages"]
assert a.propose == "a deletion tool may have run"
assert a.absence == {"looked_for": "shared_prefs", "location": "/data", "suspicious": True, "note": "gone"}
print("  OK")

print("TEST 3 — grounded finding maps correctly")
j = ('{"action":"conclude","finding":{"statement":"timeline recovered","evidence_ids":["E0001"]},'
     '"conclusion":"activity present"}')
a = r._action_from_doc(extract_first_json_object(j))
assert a.finding_statement == "timeline recovered" and a.finding_evidence_ids == ["E0001"]
print("  OK")

print("TEST 4 — real LLMReasoner drives the real bounded loop end-to-end")
script = [
    '{"thought":"look at timeline","action":"call_tool","tool_name":"read_usagestats","tool_args":{"artifact_path":"/c/usage"}}',
    '{"thought":"record it","action":"call_tool","tool_name":"read_usagestats","tool_args":{"artifact_path":"/c/usage2"},'
    '"finding":{"statement":"usage timeline recovered","evidence_ids":["E0001"]}}',
    '{"thought":"enough","action":"conclude","conclusion":"timeline artifacts present and preserved"}',
]
loop = BoundedInvestigationLoop(LLMReasoner(build_catalog(), llm=FakeLLM(script)), build_catalog(), max_steps=8)
res = loop.run()
print("  status:", res.status, "| steps:", res.steps_used, "| audit:", len(res.audit),
      "| findings:", [f.finding_id for f in res.memory.findings_list()])
assert res.status == "concluded"
assert len(res.memory.findings_list()) == 1
assert res.memory.findings_list()[0].evidence_ids == ["E0001"]
print("  OK")

print("\nALL OFFLINE TESTS PASSED")