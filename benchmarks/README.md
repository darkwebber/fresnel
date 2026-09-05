# Benchmark assets

Start with [evaluation methods and limitations](../docs/evaluation.md).
These assets are experiments, not a claim of general coding accuracy or savings.

| Asset | Status |
|---|---|
| [Resolved-IR experiment](../scripts/evaluate-resolved-ir.py) | Self-contained two-task workload; requires the configured local runtime |
| `plans/` | Legacy three-task repair plans; require external fixture repositories and tests not shipped here |
| [v0.1 summary](historical/v0.1-summary.json) | Historical worker-only totals; raw runs and exact fixtures are not included |

`scripts/run-standard-benchmark.sh /absolute/fixture-root` is retained for users
with the original `chunked`, `sessionize`, and `sql_dedup` fixtures. Its name is
historical: it is not a standardized, reproducible public benchmark. Do not
compare new results with the v0.1 totals without recovering the exact workloads,
runtime, and acceptance gates. Do not reconstruct fixtures and call them identical.

Generated reports land in ignored `benchmark-results/`; inspect and sanitize any
report before intentionally publishing it. Store IR experiment output outside the
implementation repository so failed code cannot contaminate later retrieval.

Help build [reproducible evaluations](https://github.com/darkwebber/fresnel/issues/10)
and [versioned result reports](https://github.com/darkwebber/fresnel/issues/18).
