from engine.case_memory import CaseMemory
from engine.dual_output import AuditStore
from engine.self_verification import run_self_verification

mem = CaseMemory()
audit = AuditStore()
mem.advance_step()

# Store one REAL piece of evidence -> gives E0001
receipt = audit.store("read_sharedprefs", {"entries": {"savekey_reports": "...DoD..."}})
print("stored evidence:", receipt["evidence_id"])

# H0001: a hypothesis with a GROUNDED finding, left OPEN -> 6.8 should auto-confirm it
h1 = mem.propose_hypothesis("A secure-deletion tool ran")
mem.record_finding("savekey_reports shows a DoD wipe",
                   evidence_ids=["E0001"], hypothesis_id=h1.hyp_id)

# A finding citing a FAKE evidence id -> 6.8 should FLAG it as ungrounded
mem.record_finding("logcat shows deletion of secret.pdf", evidence_ids=["E9999"])

# H0002: confirmed with NO supporting finding -> 6.8 should FLAG it
h2 = mem.propose_hypothesis("The device was encrypted")
mem.confirm_hypothesis(h2.hyp_id, reason="(premature)")

result = run_self_verification(mem, audit)

print("VERIFIED:", result.verified)
print("FLAGS:", len(result.flags))
for f in result.flags:
    print("   -", f.kind, f.subject_id, "->", f.detail)
print("AUTO-CONFIRMED (were open, now supported):", result.ready_to_confirm)
print()
print(mem.summary_for_prompt())