# Contributing to Fresnel

Welcome! Fresnel makes small local coding models useful through precise contracts,
bounded execution, independent validation, and durable recovery. We need help with
code, tests, documentation, accessibility, integrations, and honest evaluations.
You do **not** need an expensive Mac, a downloaded model, or a paid API to get started.

This is our contributor guide, not a list of people. Git history and pull requests
record contributions; please credit collaborators and upstream work in your PR.

## What we are building

Our preferred flow is:

```text
User intent → orchestrator → resolved program IR → local source generation
            → compiler + behavioral tests → targeted repair → reviewed apply
```

The orchestrator owns design, interfaces, algorithms, acceptance tests, permissions,
and final review. The local worker translates one bounded specification into code.
The harness manages evidence, tools, budgets, isolation, progress, and recovery.
“IR” currently means language-neutral implementation decisions in protocol 1.1
`implementation`, `interfaces`, and `invariants`, not a new compiler format.

Read [the handoff guide](integrations/fresnel/references/resolved-ir.md) and
[lessons from real delegations](integrations/fresnel/references/delegation.md).
We value validated useful work over impressive-looking output or benchmark claims.

### Current support versus future work

- Production runtime: Apple Silicon macOS 14+, Spark-X2.5-4B-MLX-8bit. Setup targets
  Macs with at least 16 GB unified memory. Model weights are downloaded separately.
- Core test CI: macOS and Ubuntu, Python 3.11 and 3.13. Passing Linux tests does not
  mean Linux has a supported model runtime, installer, or security boundary.
- Integrations: Codex, Cursor, OpenCode, generic CLI contract, and MCP.
- Windows/Linux product support and a first-class Claude Code adapter are proposed
  contribution tracks, not supported features yet. MLX is not a portable backend.
- Model routing remains shadow-only. New backends must not silently change the
  production worker, permissions, or privacy defaults.

## Choose your first contribution

Browse [good first issues](https://github.com/darkwebber/fresnel/labels/good%20first%20issue)
or [help wanted](https://github.com/darkwebber/fresnel/labels/help%20wanted).
Comment with your proposed approach before starting substantial work so contributors
can coordinate. Small typo/test fixes do not need a design proposal. Unassigned issues
are invitations, not promised release dates; ask questions on the issue when blocked.

### Initial contribution backlog

| Track | Issue | Suggested experience |
|---|---|---|
| MCP ready/waiting walkthrough | [#4](https://github.com/darkwebber/fresnel/issues/4) | First contribution |
| Narrow-terminal / NO_COLOR tests | [#5](https://github.com/darkwebber/fresnel/issues/5) | First contribution |
| Context budget edge tests | [#11](https://github.com/darkwebber/fresnel/issues/11) | First contribution |
| Claude Code adapter | [#3](https://github.com/darkwebber/fresnel/issues/3) | Intermediate |
| Resolved-IR evaluation and total cost | [#10](https://github.com/darkwebber/fresnel/issues/10) | Intermediate |
| Setup and calibration observability | [#13](https://github.com/darkwebber/fresnel/issues/13) | Intermediate |
| Crash/recovery fault injection | [#12](https://github.com/darkwebber/fresnel/issues/12) | Intermediate/advanced |
| Reliable code continuation | [#2](https://github.com/darkwebber/fresnel/issues/2) | Advanced |
| Platform boundaries and isolation | [#6](https://github.com/darkwebber/fresnel/issues/6) | Advanced; prerequisite for ports |
| Windows vertical slice | [#7](https://github.com/darkwebber/fresnel/issues/7) | Advanced; depends on #6 |
| Linux backend/lifecycle | [#8](https://github.com/darkwebber/fresnel/issues/8) | Advanced; depends on #6 |
| Layer streaming/offload feasibility | [#9](https://github.com/darkwebber/fresnel/issues/9) | Performance research |
| Sustained-decode calibration | [#14](https://github.com/darkwebber/fresnel/issues/14) | Intermediate/advanced |
| Retrieval and compaction evaluation | [#15](https://github.com/darkwebber/fresnel/issues/15) | Intermediate |
| Preference consent and precedence | [#16](https://github.com/darkwebber/fresnel/issues/16) | Intermediate |
| Learning evidence verification | [#17](https://github.com/darkwebber/fresnel/issues/17) | Advanced |
| Benchmark result schema and reports | [#18](https://github.com/darkwebber/fresnel/issues/18) | Intermediate |

Useful first contributions include documenting an observed failure, adding a fake
model regression, improving an error message, and testing an integration walkthrough.
For platform ports, sandbox changes, model loading, or memory architecture, agree on
an RFC/design in the issue before implementation. Keep PRs independently reviewable.

## Development without a model

Install Python 3.11+ and Git, clone the repository, and work in a virtual environment:

```bash
git clone https://github.com/darkwebber/fresnel.git
cd fresnel
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
ruff check .
fresnel --help
fresnel contract --format json
```

On Windows, use `py -3 -m venv .venv` and `.venv\Scripts\Activate.ps1` instead of
the first two environment commands. Windows test failures are currently portability
work, not evidence of supported end-to-end operation.

Alternatively, with uv installed:

```bash
uv sync --extra test
uv run pytest -q
uv run ruff check .
uv build
```

The default tests use fixtures/mocks and do not require Spark, Exa, or coordinator
credentials. Do not run `setup`, `serve`, or a real benchmark just to fix docs/tests.
CLI commands may inspect local configuration; mock home directories and use temporary
stores/workspaces when writing tests. Never test destructive operations against your
real repository or Fresnel state. CI is defined in [.github/workflows/ci.yml](.github/workflows/ci.yml).

### Optional real-model testing

Use a supported Apple Silicon Mac and follow [setup](README.md#homebrew-install).
Review download size, available storage and memory first. Run `fresnel doctor` and
record the actual runtime/model revision, hardware, profile, and sampling settings.
Keep evaluation artifacts outside the implementation repository: otherwise retrieval
can pull old failed code back into the next worker prompt.

The paired experiment in `scripts/evaluate-resolved-ir.py` requires a configured
runtime. Run it only intentionally, not in default CI. It executes generated code
using Fresnel's current sandbox; this is not a guarantee of complete isolation.

## Repository map

| Area | Starting points | Relevant tests |
|---|---|---|
| Plan/schema and orchestration | `protocol.py`, `engine.py`, `worker.py` | `test_protocol_worker.py`, `test_engine.py` |
| Ask/stream assembly and terminal output | `chat.py`, `response.py`, `terminal.py` | `test_memory_response.py`, `test_chat_sampling.py`, `test_terminal_repository.py` |
| Context, memory and recovery | `context.py`, `memory.py`, `store.py`, `workspace.py` | `test_budget_context.py`, `test_agent_os.py` |
| Tools, permissions and isolation | `capabilities.py`, `references.py`, `approvals.py`, `sandbox.py` | `test_policy_learning.py`, `test_agent_os.py` |
| Resource lifecycle/calibration | `supervisor.py`, `hardware.py`, `budget.py`, `benchmark.py` | `test_hardware.py`, `test_config_benchmark.py` |
| UX and integrations | `cli.py`, `progress.py`, `onboarding.py`, `integrations.py`, `mcp_server.py` | `test_progress.py`, `test_onboarding.py`, `test_integrations_release.py` |
| Native frontend/supervisor | `native/FresnelUI.swift`, `native/FresnelSupervisor.swift` | Native self-test and terminal/manual verification |
| Packaging | `pyproject.toml`, `scripts/`, `packaging/` | `test_runtime_install.py`, `test_integrations_release.py` |

Python source paths above are relative to `src/fresnel/`; test paths to `tests/`.
Orchestrator instructions live in `integrations/fresnel/`. Edit their source, not an
installed skill copy. The canonical contract in `integrations.py` must stay aligned
with bundled instructions and adapters.

## Engineering expectations

### Safety and compatibility

- Treat model output and retrieved documents as untrusted data, not permission grants.
- Never weaken path confinement, secret protections, or approval policy to make a
  model output pass. Use argv arrays, bounded outputs/timeouts, and scrubbed environments.
- A platform without an effective execution isolation mechanism must refuse unsafe
  worker execution or clearly restrict itself to read-only planning. The current
  non-macOS sandbox fallback is a gap to fix, not a safe porting foundation.
- Preserve protocol 1.0/1.1 compatibility, user configuration, model caches, and
  customized integration files. Include migration/rollback tests for state changes.
- Keep inference-based personalization opt-in. Never publish private prompts, source,
  credentials, paths identifying other users, or unredacted logs in issues/fixtures.
- New network access, dependencies, runtime backends, permission changes and automatic
  actions need explicit review. “Local-first” does not authorize arbitrary local reads.

### Reliability and UX

- Reproduce a bug with a focused regression before changing behavior where practical.
- Distinguish continuation (append missing text) from repair (change incorrect code).
  Never mark syntactically complete output as behaviorally validated.
- Exercise interrupted streams, repeated prefixes, malformed operations, no-progress
  loops, exhausted budgets, stale evidence, and resume idempotency.
- Every long user-facing action needs immediate feedback, phase changes and actionable
  errors. Use measured ETA or “unknown,” not fake progress. Keep machine stdout clean.
- Test TTY/non-TTY, narrow terminals, `NO_COLOR`, cancellation, and accessible linear
  output. MCP progress and CLI/TUI progress should describe the same operation.

### Resource efficiency and measurement

Prefer bounded work and minimal dependencies. Measure cold versus warm loading,
prefill versus decode, cache hits, peak memory, swap/pressure and total latency.
Report missing measurements as unavailable, not zero. Energy claims need an actual
measurement method, duration, hardware and power-source disclosure.

Layer/weight streaming and offload are research questions, not assumed wins: repeated
disk transfers can trade lower resident memory for much worse token latency and power
use. Start with a reproducible baseline, a feasibility note, an isolated experiment,
and an explicit regression threshold before production integration.

Evaluate accepted components, first-pass success, repair effort, orchestrator tokens,
worker tokens and wall time. Include failed runs. Compare equivalent acceptance gates
and disclose sample size/cache/order effects. A two-task success is not a general
success rate; lower local token usage alone does not prove lower overall cost.

## Sending a pull request

1. Branch from current `main`; link the issue and describe the intended outcome.
2. Keep the change scoped. Explain alternatives and compatibility/security effects.
3. Add behavioral tests; run `pytest -q`, `ruff check .`, and `uv build` when packaging
   or shipped resources change. Include relevant native/PTY checks for native UX work.
4. State what was actually tested and what was not. Include sanitized before/after
   metrics or screenshots for performance/UX changes. Do not fabricate a matrix run.
5. Update help/contracts/docs when user-visible behavior changes. Do not bump versions
   or publish packages/tap changes in ordinary feature PRs; maintainers coordinate releases.

AI-assisted contributions are welcome. You remain responsible for understanding the
code, licensing, safety, and tests. Disclose substantial generated implementation and
human corrections when reporting model performance. Never label an orchestrator-written
implementation as a successful worker delegation.

Review feedback is about the change, not the contributor. Be respectful, explain your
reasoning, credit others, and help keep discussions welcoming. A maintainer may ask for
a smaller experiment before accepting an architectural change.

## Reporting problems safely

For ordinary bugs, include version, OS/architecture, sanitized command/plan, expected
versus observed behavior, reproduction steps and relevant diagnostics. Report whether
the failure was model output, harness parsing, toolchain, integration, or an unknown cause.

Do not post exploitable security details or secrets publicly. If the repository offers
GitHub private vulnerability reporting, use its Security tab; otherwise open a minimal
request for a private reporting channel without exploit details. No response-time SLA
is promised. Never attach your entire Fresnel state database or model cache to an issue.

Thank you for helping make local agents reliable, measurable, and pleasant to use.
