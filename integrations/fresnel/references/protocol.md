# Protocol 1.1

This reference ships with Fresnel contract 0.5.1. Protocol 1.0 plans remain valid.

A plan is JSON with an immutable task charter: `protocol_version`, `objective`, `interfaces`, `invariants`, `contracts`, ordered `components`, `integration_validation`, and `review_checklist`.

Each component requires a stable `id`; only earlier dependency IDs; explicit repository-relative targets; interfaces and invariants; constraints; acceptance criteria; required algorithm guidance; validation commands as argv arrays; a risk envelope; and separate capability/edit/time budgets.

The worker may return only `EDIT "path"`, `CREATE "path"`, `NEEDS_CAPABILITY {json}`, legacy `NEEDS_REFERENCE {json}`, or `REQUEST_ACTION {json}`. Fresnel rejects path escapes, undeclared targets, contract edits, ambiguous replacements, incompatible protocol versions, and forward dependencies.

For small-model compatibility, `CREATE` on an existing declared target smaller than 64 KiB may become whole-file replacement inside the durable workspace. Validation and diff review remain mandatory. Capability results are bounded evidence cards with provenance, freshness, hashes, and optional continuation handles.

When exactly one Python target is declared, a response containing only syntactically valid Python (optionally in one code fence) may also be normalized into that bounded replacement. Prose or multi-target fallback is rejected.

Long operations emit progress with `phase`, `label`, `progress`, `total`, `eta_seconds`, `run_id`, optional `component_id`, and optional `attempt`. MCP hosts receive `notifications/progress`; CLI orchestrators use `--progress json` and parse `FRESNEL_PROGRESS` lines from stderr. Relay meaningful phase changes to the user.
