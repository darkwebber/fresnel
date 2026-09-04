# Fresnel 0.1.2

This patch makes hardware calibration observable instead of appearing frozen.

- Adds a live spinner and elapsed time for every benchmark probe.
- Names the active phase: model warmup, context pressure, prompt cache, or output reserve.
- Shows probe duration, free-memory percentage, and cached-token counts as results arrive.
- Prints the selected profile and calibrated context/output limits when finished.
- Keeps `--json` and redirected output machine-readable by sending no progress animation there.
- Uses the same live progress display during the benchmark phase of interactive setup.

Upgrade with `brew update && brew upgrade --yes fresnel`.
