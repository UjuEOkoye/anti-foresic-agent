"""
Test B2b — box 6.7 (ACH / W6) wired into the loop via the ANALYZE move.

Proves, with NO LLM:
  PART 1: all four innocent explanations ruled out (one only 'cannot_exclude')
          -> ACH CLEARS at REDUCED confidence.
  PART 2: an innocent explanation left 'plausible' -> ACH BLOCKED (the
          false-positive guard: you may not call it anti-forensic).
  PART 3: the LLMReasoner parses an 'alt_check' JSON into the right AgentAction.
"""
from engine.bounded_loop import (
    BoundedInvestigationLoop, FakeReasoner, AgentAction, ActionKind,
)
from engine.llm_reasoner import LLMReasoner, extract_first_json_object
from engine.tool_catalog import ToolCatalog
from engine.tool_schema import ToolSchema, FieldSpec, FieldType


def _r(artifact_path: str):
    return {"status": "ok", "artifact_path": artifact_path, "value": "x"}
TOOL = ToolSchema(name="read_sharedprefs", purpose="Read shared_prefs.",
                  args=[FieldSpec("artifact_path", FieldType.STRING, "p", required=True)],
                  output=[FieldSpec("value", FieldType.STRING, "v")], handler=_r)
def catalog():
    c = ToolCatalog(); c.register(TOOL); return c


def _alt(claim, normal, another, system, acq):
    return {"claim": claim, "assessments": [
        {"category": "normal",      "disposition": normal,  "rationale": "r"},
        {"category": "another_app", "disposition": another, "rationale": "r"},
        {"category": "system",      "disposition": system,  "rationale": "r"},
        {"category": "acquisition", "disposition": acq,     "rationale": "r"},
    ]}


print("PART 1 — all innocent stories ruled out (one cannot_exclude) -> CLEARS/REDUCED")
script1 = [
    AgentAction(thought="run the devil's-advocate check", kind=ActionKind.ANALYZE,
                alt_check=_alt("a secure-deletion tool ran",
                               "ruled_out", "ruled_out", "ruled_out", "cannot_exclude")),
    AgentAction(thought="done", kind=ActionKind.CONCLUDE, conclusion="done"),
]
r1 = BoundedInvestigationLoop(FakeReasoner(script1), catalog(), max_steps=6).run()
ach_lines1 = [e.text for e in r1.memory.full_log() if e.text.startswith("ACH[")]
print("  ", ach_lines1[0] if ach_lines1 else "(no ACH logged)")
assert ach_lines1 and "REDUCED" in ach_lines1[0]
print("  PART 1 PASS\n")

print("PART 2 — an innocent story stays 'plausible' -> BLOCKED")
script2 = [
    AgentAction(thought="check", kind=ActionKind.ANALYZE,
                alt_check=_alt("a secure-deletion tool ran",
                               "plausible", "ruled_out", "ruled_out", "ruled_out")),
    AgentAction(thought="done", kind=ActionKind.CONCLUDE, conclusion="done"),
]
r2 = BoundedInvestigationLoop(FakeReasoner(script2), catalog(), max_steps=6).run()
ach_lines2 = [e.text for e in r2.memory.full_log() if e.text.startswith("ACH[")]
print("  ", ach_lines2[0] if ach_lines2 else "(no ACH logged)")
assert ach_lines2 and "BLOCKED" in ach_lines2[0]
print("  PART 2 PASS\n")

print("PART 3 — LLMReasoner parses an 'alt_check' JSON")
j = ('{"thought":"check","action":"analyze","alt_check":{"claim":"wiping ran",'
     '"assessments":[{"category":"normal","disposition":"ruled_out","rationale":"a","evidence_ids":["E0001"]},'
     '{"category":"system","disposition":"plausible","rationale":"b"}]}}')
a = LLMReasoner(catalog(), llm=object())._action_from_doc(extract_first_json_object(j))
print("  kind:", a.kind.value, "| claim:", a.alt_check["claim"],
      "| #assessments:", len(a.alt_check["assessments"]))
assert a.kind == ActionKind.ANALYZE
assert a.alt_check["claim"] == "wiping ran"
assert len(a.alt_check["assessments"]) == 2
assert a.alt_check["assessments"][0]["evidence_ids"] == ["E0001"]
print("  PART 3 PASS\n")

print("ALL B2b TESTS PASSED — box 6.7 ACH is wired via the ANALYZE move.")