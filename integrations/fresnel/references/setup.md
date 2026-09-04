# macOS setup

This reference ships with Fresnel contract 0.4.0.

Fresnel supports Apple Silicon macOS with at least 16 GB unified memory. The default worker is the revision-pinned `abenzerps/Spark-X2.5-4B-MLX-8bit` checkpoint and pinned Spark MLX runtime.

```bash
./scripts/install-macos.sh
fresnel doctor --json
fresnel serve
fresnel benchmark --quick
fresnel integrations install codex
```

Credentials are read from environment variables first and the macOS Keychain second. The benchmark creates eco, balanced, and maximum profiles from measured context, latency, swap, and thermal behavior.
