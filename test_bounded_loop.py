import tempfile, os
from engine.bounded_loop import BoundedInvestigationLoop, FakeReasoner, AgentAction, ActionKind
from tools.registry import build_catalog

# 1. a tiny sample shared_prefs XML, so the test needs no real capture folder
sample_xml = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="savekey_reports">{"mValue":"DoD5220_22_ME","mCycles":3}</string>
    <boolean name="first_run" value="false" />
    <int name="launch_count" value="4" />
</map>"""
tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
tmp.write(sample_xml); tmp.close()

# 2. the allow-listed catalog (box 6.4)
catalog = build_catalog()

# 3. script the agent's moves (this is what the LLM will decide for real, later)
script = [
    # Step 1: form a theory + gather evidence with a VALID tool call
    AgentAction(
        thought="A wiping tool may have run. Check its shared_prefs for a wipe report.",
        kind=ActionKind.CALL_TOOL,
        tool_name="read_sharedprefs",
        tool_args={"artifact_path": tmp.name},
        propose="A secure-deletion tool ran on this device",
    ),
    # Step 2: try a HALLUCINATED tool -> the gate must REJECT it, tool never runs
    AgentAction(
        thought="Let me just delete the originals to compare.",
        kind=ActionKind.CALL_TOOL,
        tool_name="wipe_device",            # not on the allow-list
        tool_args={},
    ),
    # Step 3: record a GROUNDED finding citing the evidence from step 1, note an
    #         absence, then conclude
    AgentAction(
        thought="savekey_reports proves a DoD wipe; shared_prefs is gone post-reboot.",
        kind=ActionKind.CONCLUDE,
        finding_statement="shared_prefs contains a DoD 5220.22-M wipe report (savekey_reports)",
        finding_evidence_ids=["E0001"],
        absence={
            "looked_for": "app-private databases for the wiping app",
            "location": "/data/data/<pkg>/databases",
            "suspicious": True,
            "note": "expected but absent after uninstall+reboot",
        },
        conclusion="Artifact wiping detected: a secure-deletion tool ran (DoD 5220.22-M).",
    ),
]

# 4. run the loop
loop = BoundedInvestigationLoop(FakeReasoner(script), catalog, max_steps=12)
result = loop.run()

# 5. show what happened
print("STATUS :", result.status)
print("REASON :", result.reason)
print("STEPS  :", result.steps_used)
print("EVIDENCE IN AUDIT STORE:", len(result.audit))
print()
print(result.memory.summary_for_prompt())

os.unlink(tmp.name)  # clean up the temp file