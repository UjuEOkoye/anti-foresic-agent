from engine.case_memory import CaseMemory, CaseMemoryError

cm = CaseMemory()

cm.advance_step()                      # step 1
h = cm.propose_hypothesis(
    "A secure-deletion tool ran on this device",
    rationale="usage_stats shows a file-manager app with high launch count",
)

cm.advance_step()                      # step 2
# a grounded finding (cites evidence from the audit store)
cm.record_finding(
    "savekey_reports records a 3-pass DoD 5220.22-M wipe",
    evidence_ids=["E0001"],
    hypothesis_id=h.hyp_id,
)
cm.confirm_hypothesis(h.hyp_id, reason="corroborated by F0001")

# an absence that matters (W1)
cm.record_absence(
    looked_for="shared_prefs for the wiping app",
    location="/data/data/<pkg>/shared_prefs",
    suspicious=True,
    note="package uninstalled + device rebooted; app-private data gone",
)

# the guardrail: an ungrounded finding must be REJECTED
try:
    cm.record_finding("The user deliberately wiped evidence", evidence_ids=[])
except CaseMemoryError as e:
    print("REJECTED as expected:", e)

print()
print(cm.summary_for_prompt())