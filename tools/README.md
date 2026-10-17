# Tools

Each forensic tool the agent is allowed to call lives here as its own module
(e.g. `read_usage_stats.py`, `read_logcat.py`).

Every tool must:

1. Expose a `ToolSchema` (see `engine/tool_schema.py`) describing its name, purpose,
   argument schema, and output schema.
2. Register that schema in `engine/tool_catalog.py`.
3. Return output through `engine/dual_output.py` so a full-raw copy is preserved for
   the audit trail and only a projected summary reaches the reasoning loop.

Tools should be read-only against acquired artifacts — they inspect data that
`acquisition/` has already collected, they do not perform acquisition themselves.
