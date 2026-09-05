# Homebrew tap for Fresnel

Install Fresnel on an Apple Silicon Mac:

```bash
brew install --yes darkwebber/tap/fresnel
fresnel setup
```

Fresnel currently requires macOS 14 or newer and at least 16 GB unified memory.
The formula installs the harness; guided setup separately downloads the pinned
Spark MLX runtime and model checkpoint.

This directory contains release formula snapshots and the tap CI template.
The live tap is https://github.com/darkwebber/homebrew-tap; edits here do not
update installed packages until a maintainer publishes them there.
See [the maintainer checklist](../HOMEBREW.md).
