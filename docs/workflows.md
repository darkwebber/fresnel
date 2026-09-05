# Workflows and troubleshooting

[Documentation home](../README.md#choose-your-depth)

## Installation to first useful work

```bash
brew install --yes darkwebber/tap/fresnel
fresnel setup
fresnel doctor
fresnel onboard
```

Supported runtime: Apple Silicon macOS 14+, at least 16 GB unified memory. Setup
downloads the pinned runtime/model separately. Allow storage, network and load time;
consult `setup --help` for optional steps, not a guaranteed setup duration.
`onboard` is useful when installation is complete but host integration is not.

Choose the host you use:

```bash
fresnel integrations install codex
fresnel integrations install cursor --project /absolute/project
fresnel integrations install opencode --project /absolute/project
fresnel integrations install generic --project /absolute/project
```

For stdio MCP, configure the host to launch command `fresnel` with args `["mcp"]`.
The host needs Fresnel in PATH. Use the host's configuration mechanism; don't overwrite
unrelated settings. Restart MCP connections after upgrades.

## Reviewed implementation

Ask the orchestrator to own exact interfaces, algorithms, edge cases and independent
tests; delegate one small component and show the diff and measured effort.
Inspect [the smoke plan](../examples/smoke-plan.json) for a concrete protocol 1.0
example; 1.0 remains accepted alongside 1.1. Start in a disposable repository.

Replace the uppercase placeholders below with your paths/report run ID:

```bash
fresnel run --repo REPO --plan PLAN.json --output REPORT.json --progress json
fresnel review REPORT.json
fresnel run --resume RUN_ID --apply
```

Only apply after reviewing a passing result. Resuming the reviewed checkpoint avoids
generating a different implementation. Keep reports outside REPO so retrieval does
not pick up old failed code. Planning via `fresnel plan` needs a coordinator API;
your existing orchestrator can author plan JSON directly without another paid API.

## Questions versus edits

| `ask` | `run` |
|---|---|
| Direct answer, optional named session | Confined component execution and validation |
| No behavioral verification | Independent acceptance gates |
| Text continuation | Structured edit repair and reviewed apply |

```bash
fresnel ask "Explain iterator exhaustion" --no-copy
fresnel ask --session migration "Outline this migration"
fresnel ask --session migration --resume
```

Resume requires an interrupted named session. `--max-tokens` is per call;
`--max-total-tokens` bounds the combined generation. Pressure/headroom can reduce
limits. `--no-stream` buffers output; `--json` includes usage and completion state.

The initial interactive draft streams; continuations are checked for overlap before
displaying accepted suffixes. Completed Markdown is rendered with Glow/Termtex when
available and copied automatically in interactive use. Opt out with `--render plain`
or `--no-copy`. Incomplete answers are not automatically copied. No completion marker
or fence check proves code correctness.

## Observe, recover, diagnose

```bash
fresnel status --run RUN_ID --follow
fresnel memory inspect --run RUN_ID
fresnel run --resume RUN_ID
fresnel cancel RUN_ID
```

CLI progress goes to stderr; MCP uses notifications. Hosts may suppress them, so
use run reports/status history and relay meaningful phases to users. ETA may be unknown.

| Symptom | Check first | Avoid |
|---|---|---|
| Setup done, unsure what next | `onboard`, integration status | Re-downloading caches |
| Missing runtime executable | `doctor --json`, setup errors, `doctor --fix --help` | Changing model IDs to fix PATH |
| MCP appears idle | It waits for host protocol input | Typing chat into stdio MCP |
| Benchmark seems stuck | Progress; large prefill takes time | Assuming silence proves deadlock |
| Incomplete answer | Finish reason and continuation/total budget | Unlimited full-answer retries |
| Ask works, run fails | Endpoint/model ID, parser and validation diagnostics | Assuming identical execution paths |
| Resume rejects evidence | Source hashes may have changed | Forcing stale patches onto changed files |
| Memory pressure | Profile, cache and other workloads | Blindly raising context to 100k |

0.5.1 removed automatic whole-answer replacement, but Spark still fails some forced
short-output continuations. Prefer complete bounded code components plus tests.
When reporting problems, share a minimal sanitized reproducer—not the full database.
