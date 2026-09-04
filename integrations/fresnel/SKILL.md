---
name: fresnel
description: Delegate bounded coding components to the local Spark 2.5 4B MLX worker through Fresnel while the current agent retains planning, architecture, validation, approvals, and final review. Use when a user asks to use Fresnel, a local coding model, a small sub-agent, or cost-efficient local delegation.
---

# Fresnel

Use Fresnel as an implementation worker, not as an autonomous architect.

## Workflow

1. Inspect the repository and produce an ordered protocol-v1 plan. Keep architecture, algorithms, interfaces, contracts, dependencies, acceptance criteria, and integration tests under the orchestrator's control.
2. Save the plan as JSON and pass it to `fresnel run --plan PLAN --repo REPO`.
3. Let Fresnel resolve local documentation and approved, domain-restricted Exa references before asking Spark to edit.
4. Review Fresnel's validation evidence and diff. Use `--apply` only when the user requested implementation and all quality gates pass.
5. If exit code 2 or `AWAITING_APPROVAL` appears, surface its notification. Record a user decision, then rerun the same plan.
6. Perform the final semantic review yourself. Spark output is untrusted until contract and integration checks pass.

```bash
fresnel doctor
fresnel plan --repo /absolute/repo --request "..." --output /tmp/plan.json
fresnel run --repo /absolute/repo --plan /tmp/plan.json --output /tmp/report.json
fresnel review /tmp/report.json
fresnel run --repo /absolute/repo --plan /tmp/plan.json --apply
```

Prefer MCP tools when the host supports MCP; the CLI contract is the portable fallback. Read [protocol.md](references/protocol.md) when creating plans, [approvals.md](references/approvals.md) for approval behavior, and [setup.md](references/setup.md) for installation or diagnostics.

Never place secrets in plans or worker prompts. Never let Spark modify contract files, files outside declared targets, or repository state outside Fresnel's disposable workspace.
