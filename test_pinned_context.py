"""
Test — PINNED CONTEXT (fixes "agent amnesia").

Reproduces the live-run failure: the agent reads ONE artifact, then takes an
ANALYZE step. Before the fix, the next prompt showed only "Analysis step recorded"
— the data and the artifact list were gone, so the agent looped forever.

Proves, with NO LLM, that on every later step the agent still sees:
  1. the briefing (task + artifact inventory),
  2. the evidence it already gathered (with its evidence id),
  3. which artifacts are NOT YET READ.
"""
from engine.bounded_loop import (
    BoundedInvestigationLoop, AgentAction, ActionKind,
)
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType


def _fake_read(artifact_path: str):
    return {"status": "ok", "artifact_path": artifact_path,
            "entries": {"wipe_method": "MARKER_VALUE_123"}}

TOOL = ToolSchema(
    name="read_sharedprefs", purpose="Read an Android shared_prefs XML.",
    args=[FieldSpec("artifact_path", FieldType.STRING, "path", required=True)],
    output=[FieldSpec("entries", FieldType.OBJECT, "kv")], handler=_fake_read,
)
def catalog():
    c = ToolCatalog(); c.register(TOOL); return c


class RecordingReasoner:
    """Plays a fixed script AND records every prompt it was shown."""
    def __init__(self, script): self.script = list(script); self.seen = []
    def next_action(self, context):
        self.seen.append(context)
        return self.script.pop(0) if self.script else AgentAction(
            thought="done", kind=ActionKind.CONCLUDE, conclusion="done")


briefing = ("Investigate this capture.\nAvailable artifacts:\n"
            "- shared_prefs (1 file(s)):\n    /cap/prefs.xml\n"
            "- usage_stats (1 file(s)):\n    /cap/usage/daily/1\n")

script = [
    AgentAction(thought="read prefs", kind=ActionKind.CALL_TOOL,
                tool_name="read_sharedprefs", tool_args={"artifact_path": "/cap/prefs.xml"}),
    AgentAction(thought="think", kind=ActionKind.ANALYZE),     # the step that used to wipe context
    AgentAction(thought="think again", kind=ActionKind.ANALYZE),
]
r = RecordingReasoner(script)
BoundedInvestigationLoop(r, catalog(), max_steps=5).run(initial_observation=briefing)

step4 = r.seen[3]   # prompt shown AFTER the read + two ANALYZE steps
print("---- prompt at step 4 (excerpt) ----")
print(step4[step4.find("=== CASE BRIEFING"):step4.find("Available tools")])

assert "/cap/usage/daily/1" in step4, "briefing/inventory lost"
assert "MARKER_VALUE_123" in step4 and "[E0001]" in step4, "gathered evidence lost"
unread = step4.split("=== ARTIFACTS NOT YET READ")[1]
assert "/cap/usage/daily/1" in unread and "/cap/prefs.xml" not in unread, "unread list wrong"
print("ALL PINNED-CONTEXT TESTS PASSED — the agent no longer forgets.")