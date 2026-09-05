# Fresnel 0.5.1

- Resolved program-IR handoff and targeted repair guidance shared by bundled skills, portable integrations and MCP contract. Existing protocol 1.0/1.1 plans remain compatible.
- `ask` no longer requests automatic whole-answer replacements. Continuations are checked before displaying only their accepted suffix, and partial transport responses are retained. Conflicting restarts preserve the draft and consume the bounded continuation budget rather than overwriting accepted text. Completion remains structural, not proof of executable correctness.
- Continuation progress is explicit. First segment remains token-streamed; later segments are buffered for overlap checks. Final rendering/clipboard still receive only assembled output, and incomplete output is not automatically copied.
- Includes previously local Phoenix/C delegation fixes: narrow target-specific prompts, bounded repeated capability requests, source retrieval for C/Phoenix, and healthy external-worker reuse with corrected load telemetry.

## Paired feasibility evaluation

Spark-X2.5-4B-MLX-8bit, temperature 0.15, 768 output tokens per call; two stdlib Python tasks (sessions and interval merge), identical behavioral gates, up to one diagnostic repair per task.

| Approach | First-pass success | Success after repair | Calls | Input/output tokens | Worker seconds |
|---|---:|---:|---:|---:|---:|
| Direct task | 0/2 | 0/2 | 4 | 1,032 / 868 | 34.103 |
| Resolved IR | 2/2 | 2/2 | 2 | 414 / 540 | 23.034 |

These are small, single-trial observations, not a general success rate or cost-saving claim. Planner/reviewer effort and energy were not metered; ordering/cache effects were not controlled. IR adds explicit algorithm decisions. Reproduce with `PYTHONPATH=src python scripts/evaluate-resolved-ir.py /absolute/output`; generated code uses Fresnel's sandbox and a timeout. Keep reports outside the implementation repository.

Forced 128/256-token code continuation stress tests still exposed Spark suffix errors and repeated premature stops. The tightened fence parser now rejects language-tagged pseudo-closing fences, and exhaustion reports incomplete rather than silently replacing the draft. This patch fixes the whole-answer replay policy; it does not make arbitrary mid-code continuation reliable. Prefer independently complete IR components with sufficient output budget and executable gates.

## Upgrade

Run `brew update` then `brew upgrade darkwebber/tap/fresnel`. Refresh each installed adapter with `fresnel integrations sync <adapter>` (use `--project` for project integrations). User-modified instructions are preserved; inspect integration status/diffs rather than overwriting customizations. Restart the host's Fresnel MCP process to load the new version.

The runtime wheel remains pinned to the existing immutable 0.5.0 runtime asset; model caches are preserved. Tester binaries are ad-hoc signed, not Apple notarized. Hardware coverage is this local Apple Silicon machine; the release does not claim the full M2/M3/M4 matrix.
