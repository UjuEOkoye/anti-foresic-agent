# Anti-Forensic Agent

An investigative agent that analyzes mobile device artifacts (usage stats, logcat,
app behavior, etc.) to detect and characterize anti-forensic behavior — e.g. "cleaner"
apps and techniques used to destroy or obscure evidence.

## Design principles

- **Allow-listed tools only.** The agent can only call tools registered in
  `engine/tool_catalog.py`. Every call is validated against its schema
  (`engine/validation_gate.py`) before execution.
- **Dual output.** Every tool result is split into a full-raw copy (preserved in
  `audit_store/` for the final report and chain of custody) and a projected/summarized
  copy that's actually fed into the reasoning loop (`engine/dual_output.py`). This keeps
  the agent's context small without losing the underlying evidence.
- **Bounded loop.** The agent runs a plan -> validate -> execute -> observe loop with a
  hard step budget (`engine/bounded_loop.py`), so it terminates predictably.
- **Case memory.** Findings, hypotheses, and history accumulate in
  `engine/case_memory.py` across the run and feed the final report.
- **Knowledge, not tools, in `knowledge_base/`.** That directory holds behavior classes,
  artifact signatures, and normal-usage baselines — not tool implementations.
- **Evaluation is separate from the agent.** `evaluation/` holds the test harness,
  ground-truth labels, and metrics, and never leaks into `engine/` or `tools/`.

## Layout

- `config/` — global configuration (model, paths, step budget)
- `engine/` — the core agent loop and its supporting types
- `tools/` — forensic tool implementations (read_usage_stats, read_logcat, etc.)
- `knowledge_base/` — behavior classes, artifact signatures, normal baselines
- `acquisition/` — scripted acquisition/collection of artifacts from a device (reuses
  CleanerScope's adb tooling)
- `audit_store/` — full-raw tool outputs preserved for the final report
- `reporting/` — assembles the final forensic report
- `evaluation/` — test harness, ground-truth labels, metrics (kept separate from the agent)
- `data/` — test artifact sets (Tier 1/2/3 cases)
- `main.py` — entry point that wires everything together

## Getting started

```
pip install -r requirements.txt
python main.py --help
```
