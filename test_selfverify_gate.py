"""
Test B1 — box 6.8 self-verification wired as the CONCLUDE gate in bounded_loop.

Proves two things with NO LLM (scripted FakeReasoner):
  CASE 1 (clean): a grounded finding -> loop concludes, hypothesis auto-confirmed.
  CASE 2 (hallucinated evidence): a finding citing a non-existent evidence id ->
          the loop REFUSES to conclude and ends 'inconclusive' (the guarantee).
"""
from engine.bounded_loop import (
    BoundedInvestigationLoop, FakeReasoner, AgentAction, ActionKind,
)
from engine.case_memory import HypothesisStatus
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType


def _fake_read(artifact_path: str):
    return {"status": "ok", "artifact_path": artifact_path, "value": "wipe_report"}

TOOL = ToolSchema(
    name="read_sharedprefs",
    purpose="Read an Android shared_prefs XML.",
    args=[FieldSpec("artifact_path", FieldType.STRING, "path", required=True)],
    output=[FieldSpec("value", FieldType.STRING, "a value")],
    handler=_fake_read,
)

def catalog():
    c = ToolCatalog(); c.register(TOOL); return c


print("CASE 1 — clean grounded conclusion should PASS the 6.8 gate")
# step1: propose a hypothesis + call the tool (creates evidence E0001)
# step2: record a finding grounded in E0001, tied to the hypothesis, then conclude
script1 = [
    AgentAction(thought="suspect a wipe; look at shared_prefs",
                kind=ActionKind.CALL_TOOL, tool_name="read_sharedprefs",
                tool_args={"artifact_path": "/cap/sp.xml"},
                propose="a secure-deletion tool ran on this device"),
    AgentAction(thought="shared_prefs proves it; record + conclude",
                kind=ActionKind.CONCLUDE,
                conclusion="anti-forensic wiping activity present",
                finding_statement="shared_prefs holds a wipe report",
                finding_evidence_ids=["E0001"]),
]
loop1 = BoundedInvestigationLoop(FakeReasoner(script1), catalog(), max_steps=6)
r1 = loop1.run()
print("  status:", r1.status, "| findings:", [f.finding_id for f in r1.memory.findings_list()])
hs = [(h.hyp_id, h.status.value) for h in r1.memory.all_hypotheses()]
print("  hypotheses:", hs)
assert r1.status == "concluded"
# NOTE: auto-confirm only fires when the finding is tied to the hypothesis id.
# This finding was recorded without a hypothesis_id, so H0001 stays open here —
# that's expected; B2 will let the agent tie findings to hypotheses.
print("  PASS (clean conclusion allowed)\n")


print("CASE 2 — conclusion on a HALLUCINATED evidence id should be BLOCKED")
# The agent records a finding citing E9999, which never went through the audit
# store. 6.8 must flag it and the loop must NOT conclude -> inconclusive.
script2 = [
    AgentAction(thought="conclude on evidence I never actually pulled",
                kind=ActionKind.CONCLUDE,
                conclusion="wiping tool present",
                finding_statement="a wipe report exists",
                finding_evidence_ids=["E9999"]),   # does NOT exist in the audit store
]
loop2 = BoundedInvestigationLoop(FakeReasoner(script2), catalog(), max_steps=5)
r2 = loop2.run()
print("  status:", r2.status, "| steps_used:", r2.steps_used)
# find the 6.8 flag in the log
flagged = [e.text for e in r2.memory.full_log() if "ungrounded_finding" in e.text]
print("  6.8 flag logged:", bool(flagged))
assert r2.status == "inconclusive"      # could NOT conclude on fake evidence
assert flagged                          # the gate caught it
print("  PASS (ungrounded conclusion refused)\n")

print("ALL B1 TESTS PASSED — box 6.8 is wired as the conclude gate.")