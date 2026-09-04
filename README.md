# Fresnel

Fresnel is a Mac-native orchestration harness that lets strong coordinators such
as Codex, Cursor, or OpenCode delegate bounded coding components to a local
Spark 2.5 MLX worker. It owns contracts, references, approvals, disposable
workspaces, validation, assembly, and cost/quality metrics.

## Homebrew install

```bash
brew install --yes darkwebber/tap/fresnel
fresnel setup
```

The explicit `--yes` avoids Homebrew 6's default confirmation prompt in
embedded terminals. It does not disable tap-trust checks. Interactive setup
finishes with a terminal walkthrough that configures the background worker and
your Codex, Cursor, OpenCode, or generic integration.

Already ran setup and are wondering what comes next? Run:

```bash
fresnel onboard
```

## Ask and sampling

Use the local model directly for a small one-off question:

```bash
fresnel ask "Write a PySpark expression that normalizes an email column"
```

Answers stream to the terminal by default. If the server reaches its token
ceiling, Fresnel continues the same answer up to two times while preserving the
original question. Use `--max-continuations 0` to disable continuation,
`--no-stream` to buffer the answer, or `--json` for machine-readable call and
budget metrics. Requested output is reduced automatically when context headroom
or current Mac memory pressure makes the requested ceiling unsafe.

Fresnel keeps hardware pressure measurements at temperature 0 so repeated
calibrations are comparable. Normal worker calls use the sampling values in the
active profile (`balanced` defaults to temperature 0.15). Tune behavior locally:

```bash
fresnel tune
fresnel config sampling --temperature 0.25 --top-p 0.9 --top-k 40
```

Per-question overrides are available through `fresnel ask --help`.

For an explicit, repository-scoped conversation, name it and resume an
interrupted answer without replaying the prompt:

```bash
fresnel ask --session migration "Plan the Scala migration"
fresnel ask --session migration "Now implement the encoder"
fresnel ask --session migration --resume
```

Interactive drafts use a temporary terminal screen. A completed answer is then
rendered once through the pinned `termtex` math renderer and Glow, and its raw
Markdown is copied to the clipboard. JSON, piped output, errors, and interrupted
answers are never copied. Use `--render plain` or `--no-copy` to opt out.

## Development install

```bash
./scripts/install-macos.sh
```

Or install directly:

```bash
uv tool install '.[setup]'
fresnel setup
```

Run diagnostics and calibration:

```bash
fresnel doctor
fresnel serve
fresnel benchmark
```

`fresnel setup` checks Apple Silicon and memory, installs revision-pinned runtime
and model artifacts, starts a temporary worker, and runs an adaptive 5–10 minute
calibration. It saves `eco`, `balanced`, and `maximum` profiles; change one later
with `fresnel config profile eco|balanced|maximum`. Credentials stay in macOS
Keychain, not project files.

Delegate a reviewed plan without touching the real repository:

```bash
fresnel run --repo /path/to/repo --plan plan.json --output review.json
fresnel review review.json
```

Interactive commands show a spinner, current phase, elapsed time, validation
state, and an ETA once Fresnel has enough evidence to estimate one. Automation
can request the same stream as newline-delimited events with `--progress json`.
Each final run report also retains its progress history, so an orchestrator can
replay status even if its client does not display live notifications.

Fresnel uses the configured local snapshot path as the worker model ID. If an
OpenAI-compatible server rejects that ID with HTTP 404, it retries once without
the model field so the server can select its advertised default. The fallback
is recorded in run metrics instead of being hidden.

Use `--apply` only after reviewing a passing result. Fresnel currently routes
all real worker calls to Spark 2.5 4B MLX 8-bit; future routing runs in shadow
mode until benchmark evidence supports activation.

## Small-model context management

The coordinator owns the durable goal and plan. Every worker retry restates the
overall goal, bounded task, constraints, acceptance checks, and implementation
contract. Fresnel reads declared files from its disposable on-disk workspace,
fits compact head/tail excerpts into a pressure-aware input budget, and lets the
worker request a specific 1–400 line excerpt when omitted code is needed. Local
excerpt requests are auto-approved; undeclared paths and path escapes are
rejected.

Worker output that ends with `finish_reason=length` is never parsed or applied.
The partial output is recorded for observability and Fresnel retries with a
smaller-edit instruction. Input budgets shrink on retries and under memory
pressure, while output headroom is calculated from the actual prompt instead of
assuming the configured 4096-token default is always sufficient. Run reports
include truncation retries, on-demand excerpt reads, and pressure events.

Fresnel also stores a versioned task charter, append-only events, a deterministic
current-situation view, sparse repository evidence, validation results, and
content-addressed compressed raw artifacts. The compact state is retained;
unpinned raw blobs expire after 30 days. Inspect, replay, pin, garbage-collect,
or deliberately forget memory with `fresnel memory --help`.

## Orchestrator integrations

```bash
fresnel integrations install codex
fresnel integrations install cursor --project /path/to/repo
fresnel integrations install opencode --project /path/to/repo
fresnel integrations install generic --project /path/to/repo
```

Every adapter points at the same protocol and CLI/MCP surface, so policy does
not drift between products. Existing adapter files are backed up. Installations
are reversible with `fresnel integrations uninstall ...`. Registered,
unmodified adapters auto-sync across Fresnel upgrades; locally modified adapters
are preserved and reported by `fresnel integrations status`, `diff`, and
`repair`. `fresnel contract --format json` is the tool-neutral source of truth.

`fresnel mcp` prints an immediate ready/waiting message when started directly in
a terminal. Under Cursor or another MCP host it preserves stdout for JSON-RPC,
then emits standard MCP progress notifications for planning, worker attempts,
retries, validation, approvals, completion, and ETA. Integration rules require
the orchestrator to relay these updates to the user instead of going silent.

## Metrics and learning

Each run persists coordinator input/output tokens and estimated API cost, local
worker input/output/cached tokens, attempts, latency, validation outcomes,
approval events, and failure signatures in SQLite. Configure pricing with
`fresnel config pricing --input USD_PER_MILLION --output USD_PER_MILLION`.
`fresnel learn` proposes a harness change only after the same normalized failure
appears at least three times across two runs. Proposals are never activated
automatically; the included promotion gates require regression and cost checks.

The 8-bit worker currently has strengths declared for bounded Python edits,
simple file creation, and mechanical repairs. Multi-model routing remains shadow
only in v0.1, making future model additions observable before they affect work.

The included three-task standard suite can be rerun with
`scripts/run-standard-benchmark.sh /path/to/harness_eval`. The measured v0.1
result and comparison with earlier runs are saved in
`benchmark-results/summary.json`.

Build a small shareable tester archive with `scripts/build-tester-bundle.sh`.
The model is deliberately not embedded; guided setup downloads and verifies the
revision-pinned checkpoint on each tester's Mac.
