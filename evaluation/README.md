# Evaluation

Test harness, ground-truth labels, and metrics for measuring the agent's performance —
kept deliberately separate from `engine/` and `tools/` so evaluation logic never leaks
into the agent itself.

Expected contents:

- A harness that runs the agent against the Tier 1/2/3 cases in `data/` and captures
  its findings.
- Ground-truth labels for each case (what anti-forensic behavior, if any, is actually
  present).
- Metrics comparing agent findings against ground truth (precision/recall per behavior
  class, false-positive rate, etc.).
