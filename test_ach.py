from engine.case_memory import CaseMemory
from engine.ach import (
    AltCategory, Disposition, AltAssessment, run_ach_stage
)

mem = CaseMemory()
mem.advance_step()

# --- Claim A: should CLEAR, but at REDUCED confidence (one cannot-exclude) ---
claim_a = "A wiping tool securely deleted report_2024.pdf"
assessments_a = [
    AltAssessment(AltCategory.NORMAL, Disposition.RULED_OUT,
                  "savekey_reports shows a 3-pass DoD overwrite, not a normal delete",
                  evidence_ids=["E0001"]),
    AltAssessment(AltCategory.ANOTHER_APP, Disposition.RULED_OUT,
                  "only this package references the file in any artifact", ["E0001", "E0002"]),
    AltAssessment(AltCategory.SYSTEM_BEHAVIOR, Disposition.RULED_OUT,
                  "the path is app-private, not a system-managed location"),
    AltAssessment(AltCategory.ACQUISITION_LIMIT, Disposition.CANNOT_EXCLUDE,
                  "device was rebooted before capture; some volatile data may be lost"),
]
res_a = run_ach_stage(mem, claim_a, assessments_a)
print("CLAIM A:", res_a.confidence.upper())
print("   ", res_a.verdict())

# --- Claim B: should be BLOCKED (a normal explanation is still plausible) ---
claim_b = "Bulk file deletion indicates anti-forensic wiping"
assessments_b = [
    AltAssessment(AltCategory.NORMAL, Disposition.PLAUSIBLE,
                  "a file-manager app normally does bulk deletes; looks identical"),
    AltAssessment(AltCategory.ANOTHER_APP, Disposition.CANNOT_EXCLUDE,
                  "a second cleaner app is also installed"),
    AltAssessment(AltCategory.SYSTEM_BEHAVIOR, Disposition.RULED_OUT,
                  "not a system path"),
    AltAssessment(AltCategory.ACQUISITION_LIMIT, Disposition.RULED_OUT,
                  "full capture confirmed for this location"),
]
res_b = run_ach_stage(mem, claim_b, assessments_b)
print("CLAIM B:", res_b.confidence.upper())
print("   ", res_b.verdict())

print()
print(mem.summary_for_prompt())