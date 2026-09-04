---
name: fresnel
description: Orchestrate cost-efficient local implementation through Fresnel while retaining architecture, decomposition, approvals, validation, memory policy, and final review. Use when a user asks for Fresnel, a local coding model, a small sub-agent, or local delegation.
---

# Fresnel

Contract version: 0.4.0. The current external agent is Fresnel's brain and taste-maker.
Spark is a bounded implementation worker, never the architect or final reviewer.

## Workflow

1. Inspect the repository and understand the user's actual goal before delegation.
2. Own the architecture, algorithms, interfaces, contracts, decomposition, dependencies, acceptance criteria, and integration tests. Produce an ordered protocol-v1 plan with small components.
3. Give each component explicit targets, read-only context, constraints, required implementation details, validation argv arrays, and only earlier dependencies.
4. Save the plan and pass it to `fresnel run --plan PLAN --repo REPO`.
5. Let Fresnel resolve local documentation first and approved, domain-restricted Exa references only when the plan authorizes them.
6. Review validation evidence and the complete diff. Use `--apply` only when implementation was requested and all quality gates pass.
7. If exit code 2 or `AWAITING_APPROVAL` appears, surface the notification. Record the user's decision, then resume the same run or plan.
8. Perform the final semantic review yourself. Spark output is untrusted until protocol, component, integration, and human-quality checks pass.

```bash
fresnel doctor
fresnel plan --repo /absolute/repo --request "..." --output /tmp/plan.json
fresnel run --repo /absolute/repo --plan /tmp/plan.json --output /tmp/report.json
fresnel review /tmp/report.json
fresnel run --repo /absolute/repo --plan /tmp/plan.json --apply
fresnel memory inspect --run RUN_ID
fresnel contract --format json
```

Prefer MCP tools when the host supports MCP; the CLI contract is the portable fallback. Read [protocol.md](references/protocol.md) when creating plans, [approvals.md](references/approvals.md) for approval behavior, [memory.md](references/memory.md) for replay and retrieval, and [setup.md](references/setup.md) for diagnostics.

Never place secrets in plans or worker prompts. Never let Spark modify contract files, files outside declared targets, or repository state outside Fresnel's disposable workspace.

Report validation, applied state, coordinator/worker tokens, cache hits, retries, reference reads, latency, and pending approvals. If a run is interrupted, reconstruct it from Fresnel memory and repository evidence instead of pasting old transcripts into Spark.
