"""
Test — reply validation (fixes the "Tool '' is not in the allow-list" loop).

In the live run the model sometimes replied with JSON that was NOT an action
(no "action", no "tool_name" — e.g. a copy of evidence). It parsed fine, so it
was treated as call_tool with an empty tool name and rejected, step after step.

Proves, with NO LLM:
  1. a parsed-but-not-an-action reply triggers the repair retry, and the
     repaired valid action is used;
  2. if the repair also fails, the reasoner returns a no-op ANALYZE (the run
     continues) instead of an empty call_tool or ending the investigation;
  3. the context-window setting is read from OLLAMA_NUM_CTX.
"""
import inspect
from engine.llm_reasoner import LLMReasoner, is_valid_action_doc, _build_llm
from engine.bounded_loop import ActionKind
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType


class FakeReply:
    def __init__(self, c): self.content = c
class FakeLLM:
    def __init__(self, s): self.s = list(s)
    def invoke(self, prompt): return FakeReply(self.s.pop(0))

TOOL = ToolSchema(name="read_logcat", purpose="Read logcat.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("lines", FieldType.LIST, "l")], handler=lambda artifact_path: {})
cat = ToolCatalog(); cat.register(TOOL)

print("TEST 1 — validator")
assert not is_valid_action_doc({"status": "ok", "entries": {}})          # echoed evidence
assert not is_valid_action_doc({"action": "call_tool", "tool_name": ""}) # empty tool
assert is_valid_action_doc({"action": "call_tool", "tool_name": "read_logcat"})
assert is_valid_action_doc({"action": "analyze"})
print("  OK")

print("TEST 2 — junk reply -> repair -> valid action used")
r = LLMReasoner(cat, llm=FakeLLM([
    '{"status":"ok","artifact_path":"/x","entries":{"a":"b"}}',
    '{"thought":"read logcat","action":"call_tool","tool_name":"read_logcat","tool_args":{"artifact_path":"/l"}}',
]))
a = r.next_action("state")
assert a.kind == ActionKind.CALL_TOOL and a.tool_name == "read_logcat", a
print("  OK")

print("TEST 3 — junk twice -> no-op ANALYZE (run continues), snippet logged")
r = LLMReasoner(cat, llm=FakeLLM(['{"status":"ok"}', '{"foo":1}']))
a = r.next_action("state")
assert a.kind == ActionKind.ANALYZE and "INVALID REPLY" in a.thought, a
print("  OK  thought =", a.thought)

print("TEST 4 — context window comes from OLLAMA_NUM_CTX")
assert "OLLAMA_NUM_CTX" in inspect.getsource(_build_llm) and "num_ctx" in inspect.getsource(_build_llm)
print("  OK")

print("\nALL REPLY-VALIDATION TESTS PASSED")
print("\nTEST 5 — Qwen3 <think> block is stripped before reading the JSON")
from engine.llm_reasoner import strip_thinking
r = LLMReasoner(cat, llm=FakeLLM([
    '<think>The file has {"weird": braces} in it. I should read logcat.</think>\n'
    '{"thought":"read logcat","action":"call_tool","tool_name":"read_logcat","tool_args":{"artifact_path":"/l"}}'
]))
a = r.next_action("state")
assert a.kind == ActionKind.CALL_TOOL and a.tool_name == "read_logcat", a
assert strip_thinking("no think here {}") == "no think here {}"
print("  OK")
print("ALL REPLY-VALIDATION TESTS PASSED (incl. Qwen3 thinking)")