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

Fresnel keeps hardware pressure measurements at temperature 0 so repeated
calibrations are comparable. Normal worker calls use the sampling values in the
active profile (`balanced` defaults to temperature 0.15). Tune behavior locally:

```bash
fresnel tune
fresnel config sampling --temperature 0.25 --top-p 0.9 --top-k 40
```

Per-question overrides are available through `fresnel ask --help`.

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

Use `--apply` only after reviewing a passing result. Fresnel currently routes
all real worker calls to Spark 2.5 4B MLX 8-bit; future routing runs in shadow
mode until benchmark evidence supports activation.

## Orchestrator integrations

```bash
fresnel integrations install codex
fresnel integrations install cursor --project /path/to/repo
fresnel integrations install opencode --project /path/to/repo
fresnel integrations install generic --project /path/to/repo
```

Every adapter points at the same protocol and CLI/MCP surface, so policy does
not drift between products. Existing adapter files are backed up. Installations
are reversible with `fresnel integrations uninstall ...`.

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
