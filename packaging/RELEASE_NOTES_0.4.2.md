# Fresnel 0.4.2

This release fixes compatibility with Spark servers that advertise a filesystem
snapshot as their model identifier. Worker runs now use the configured snapshot
path and, if the server still rejects that identifier with HTTP 404, retry once
without a model field so the server can select its default. The selected ID and
fallback count are visible in diagnostics and metrics.

Long-running setup, planning, worker, retry, validation, approval, benchmark,
and completion phases now expose consistent progress, elapsed state, and ETA:

- terminals receive live haptics automatically;
- CLI orchestrators can select `--progress json`;
- MCP clients receive standard progress or logging notifications;
- final run reports retain progress history for clients that cannot stream;
- direct `fresnel mcp` launches display an immediate readiness message.

The doctor report also shows the server's advertised model IDs and Fresnel's
selected worker ID, making configuration mismatches visible before a run.
