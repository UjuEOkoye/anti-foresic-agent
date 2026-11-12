"""
Test: the knowledge base (box 6.2) is wired into the loop's context.

PART 1: with a KB attached, once the agent has an AW-ish open hypothesis, the
        context the reasoner sees includes the relevant WIPING card, labelled as
        general background (not evidence).
PART 2: with NO KB attached, the context has no knowledge block (backward compatible).
PART 3: a full scripted run still works with a KB attached (nothing breaks).
"""
from engine.bounded_loop import BoundedInvestigationLoop, FakeReasoner, AgentAction, ActionKind
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType
from knowledge_base import build_knowledge_base


def _r(artifact_path: str):
    return {"status": "ok", "artifact_path": artifact_path, "value": "x"}
TOOL = ToolSchema(name="read_sharedprefs", purpose="Read shared_prefs.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("value", FieldType.STRING, "v")], handler=_r)
def catalog():
    c = ToolCatalog(); c.register(TOOL); return c


print("PART 1 — with a KB, the context carries the relevant background card")
loop = BoundedInvestigationLoop(FakeReasoner([]), catalog(), knowledge_base=build_knowledge_base())
# the agent has formed an AW hypothesis
loop.memory.propose_hypothesis("a secure-deletion tool overwrote files on this device")
context = loop._build_context("multiple overwrite passes were recorded")
print("  has knowledge block:", "RELEVANT FORENSIC KNOWLEDGE" in context)
print("  mentions wiping card:", "Artifact wiping" in context or "overwriting" in context)
assert "RELEVANT FORENSIC KNOWLEDGE" in context
assert "NOT evidence" in context                      # labelled as background, not evidence
assert "wiping" in context.lower()                    # the AW card was retrieved
print("  PART 1 PASS\n")

print("PART 2 — with NO KB, the context has no knowledge block")
loop_nokb = BoundedInvestigationLoop(FakeReasoner([]), catalog())   # knowledge_base=None
loop_nokb.memory.propose_hypothesis("a secure-deletion tool overwrote files")
ctx2 = loop_nokb._build_context("multiple overwrite passes were recorded")
print("  has knowledge block:", "RELEVANT FORENSIC KNOWLEDGE" in ctx2)
assert "RELEVANT FORENSIC KNOWLEDGE" not in ctx2
print("  PART 2 PASS\n")

print("PART 3 — a full scripted run still works with a KB attached")
script = [
    AgentAction(thought="look at shared_prefs", kind=ActionKind.CALL_TOOL,
                tool_name="read_sharedprefs", tool_args={"artifact_path": "/cap/sp.xml"},
                propose="a secure-deletion tool ran"),
    AgentAction(thought="done", kind=ActionKind.CONCLUDE, conclusion="analysis complete"),
]
res = BoundedInvestigationLoop(FakeReasoner(script), catalog(),
                               knowledge_base=build_knowledge_base(), max_steps=6).run()
print("  status:", res.status, "| steps:", res.steps_used)
assert res.status == "concluded"
print("  PART 3 PASS\n")

print("ALL KB-WIRING TESTS PASSED — the agent now reasons WITH its textbook.")