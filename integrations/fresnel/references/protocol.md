# Protocol v1

This reference ships with Fresnel contract 0.4.1.

A plan is JSON with `protocol_version`, `objective`, `contracts`, ordered `components`, `integration_validation`, and `review_checklist`.

Each component requires a stable `id`; only earlier dependency IDs; explicit repository-relative targets; optional read-only context files; constraints; acceptance criteria; implementation guidance; validation commands as argv arrays; and structured reference requests.

The worker may return only `EDIT "path"`, `CREATE "path"`, `NEEDS_REFERENCE {json}`, or `REQUEST_ACTION {json}`. Fresnel rejects path escapes, undeclared targets, contract edits, ambiguous replacements, incompatible protocol versions, and forward dependencies.

For small-model compatibility, `CREATE` on an existing declared target smaller than 64 KiB may become whole-file replacement inside the disposable workspace. Validation and diff review remain mandatory.

When exactly one Python target is declared, a response containing only syntactically valid Python (optionally in one code fence) may also be normalized into that bounded replacement. Prose or multi-target fallback is rejected.
