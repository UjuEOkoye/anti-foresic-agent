# Knowledge Base

Reference knowledge the agent reasons with — not tool implementations. This is where
domain expertise lives so it can be inspected, versioned, and updated independently of
the engine and tools.

Expected contents:

- **Behavior classes** — categories of anti-forensic behavior (e.g. selective log
  deletion, timestamp manipulation, cache/usage-stats wiping, cloner/dual-app evasion).
- **Artifact signatures** — the specific traces each behavior class leaves behind in
  usage stats, logcat, package state, etc.
- **Normal baselines** — what unremarkable device usage looks like, so deviations are
  meaningful rather than noise.

Keep this data-only (YAML/JSON/Markdown) wherever practical — it should be readable by
a human reviewer without executing any code.
