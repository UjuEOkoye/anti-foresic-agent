from engine.case_memory import CaseMemory
from engine.correlation import Observation, ExpectedArtifact, run_correlation

mem = CaseMemory()
mem.advance_step()   # step 1

# Observations the agent "extracted" from evidence (LLM's job, faked here):
observations = [
    # same wiped filename seen in TWO sources -> should CORROBORATE
    Observation(source_id="E0001", claim_key="wiped_file", value="report_2024.pdf"),
    Observation(source_id="E0002", claim_key="wiped_file", value="report_2024.pdf"),
    # two sources disagree on the device timezone -> should CONFLICT
    Observation(source_id="E0003", claim_key="device_timezone", value="America/Chicago"),
    Observation(source_id="E0004", claim_key="device_timezone", value="America/New_York"),
]

# What the agent EXPECTED to find for a suspected wiping app:
expected = [
    ExpectedArtifact(
        label="shared_prefs for the wiping app",
        locator="/data/data/pkg/shared_prefs/app.xml",
        reason="a wiping app normally stores a wipe report here",
    ),
    ExpectedArtifact(
        label="app-private database for the wiping app",
        locator="/data/data/pkg/databases/app.db",
        reason="the app normally keeps a job database",
    ),
]
# Only the shared_prefs was actually found; the database is MISSING.
present_locators = {"/data/data/pkg/shared_prefs/app.xml"}

result = run_correlation(mem, observations, expected, present_locators)

print("CORROBORATIONS:", len(result.corroborations))
for c in result.corroborations:
    print("   ", c.claim_key, "=", c.value, "<-", c.sources)
print("CONFLICTS:", len(result.conflicts))
for cf in result.conflicts:
    print("   ", cf.claim_key, cf.values_by_source)
print("ABSENCES:", len(result.absences))
for ab in result.absences:
    print("   ", ab.label, "(" + ab.locator + ")")
    print("      candidates:", len(ab.candidate_explanations), "(missing != deleted)")
print()
print(mem.summary_for_prompt())