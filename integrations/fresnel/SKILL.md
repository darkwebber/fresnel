---
name: fresnel
description: Orchestrate cost-efficient local implementation through Fresnel while retaining architecture, decomposition, approvals, validation, memory policy, and final review. Use when a user asks for Fresnel, a local coding model, a small sub-agent, or local delegation.
---

# Fresnel

Contract version: 0.5.0 / protocol 1.1. The external agent is Fresnel's architect and reviewer.
Spark is a bounded implementation worker, never the architect or final reviewer.

## Workflow

1. Inspect the repository and understand the user's actual goal before delegation.
2. Own the architecture, algorithms, interfaces, invariants, contracts, decomposition, dependencies, acceptance criteria, risk envelopes, and integration tests. Produce an ordered protocol-1.1 plan with small components; protocol 1.0 remains accepted.
3. Give each component explicit targets, read-only context, constraints, required implementation details, validation argv arrays, and only earlier dependencies.
4. Save the plan and pass it to `fresnel run --plan PLAN --repo REPO`.
5. Let Fresnel resolve local documentation first and approved, domain-restricted Exa references only when the plan authorizes them.
6. Review validation evidence and the complete diff. Use `--apply` only when implementation was requested and all quality gates pass.
7. If exit code 2 or `AWAITING_APPROVAL` appears, surface the notification. Record the user's decision, then resume the same run or plan.
8. Perform the final semantic review yourself. Spark output is untrusted until protocol, component, integration, and human-quality checks pass.
9. Relay Fresnel progress to the user: current phase, component/attempt, completed/total, ETA, retries, and validation state. MCP emits these as progress notifications; CLI orchestration should use `--progress json`. Never leave a long-running delegation looking idle.

For greenfield applications or repeated worker failures, read [delegation.md](references/delegation.md). It records tested component-sizing, validation, and retry practices from the Phoenix sand simulation and C terminal game evaluations.

```bash
fresnel doctor
fresnel plan --repo /absolute/repo --request "..." --output /tmp/plan.json
fresnel run --repo /absolute/repo --plan /tmp/plan.json --output /tmp/report.json --progress json
fresnel status --run RUN_ID --follow
fresnel run --resume RUN_ID
fresnel review /tmp/report.json
fresnel run --resume RUN_ID --apply
fresnel memory inspect --run RUN_ID
fresnel contract --format json
```

Prefer MCP tools when the host supports MCP; the CLI contract is the portable fallback. MCP tool calls provide live progress notifications. If the host suppresses notifications, tell the user the last known phase before waiting and include the final progress history from the result. Read [protocol.md](references/protocol.md) when creating plans, [approvals.md](references/approvals.md) for approval behavior, [memory.md](references/memory.md) for replay and retrieval, and [setup.md](references/setup.md) for diagnostics.

Never place secrets in plans or worker prompts. Never let Spark modify contract files, files outside declared targets, or repository state outside Fresnel's confined durable workspace.

Report validation, applied state, coordinator/worker tokens, cache hits, retries, capability reads, latency, resource pressure, and pending approvals. If a run is interrupted, use `fresnel run --resume RUN_ID`; Fresnel restores the last verified checkpoint and rejects stale source evidence.
