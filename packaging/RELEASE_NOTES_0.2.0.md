# Fresnel 0.2.0

Fresnel now separates repeatable hardware measurement from creative worker sampling.

- Adds `fresnel ask` for direct, inexpensive one-off questions to the local Spark model.
- Adds `fresnel tune`, a lightweight behavioral sampling tuner.
- Adds manual `temperature`, `top_p`, `top_k`, and `min_p` controls per active profile.
- Changes the balanced worker default from greedy decoding to temperature 0.15.
- Keeps hardware pressure probes at temperature 0 for apples-to-apples calibration.
- Gives eco, balanced, and maximum profiles temperatures 0.0, 0.15, and 0.25 respectively.
- Migrates existing configuration profiles safely when the new sampling fields are absent.
- Shows sampling temperature in onboarding and limits one-off output to safe profile bounds.

Examples:

```bash
fresnel ask "Explain this PySpark error"
fresnel tune
fresnel config sampling --temperature 0.25 --top-p 0.9 --top-k 40
```
