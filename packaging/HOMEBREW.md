# Publishing Fresnel with Homebrew

## Current distribution: a personal tap

A personal tap has no Homebrew maintainer review queue. Create a public upstream
repository and immutable GitHub release, then use the separate public
repository named `homebrew-tap` containing `Formula/fresnel.rb`. Once both are
pushed, testers can install immediately:

```bash
brew install OWNER/tap/fresnel
```

Before pushing the formula:

1. Replace the placeholder homepage with the canonical Fresnel repository.
2. Point `url` at the immutable versioned `fresnel_agent-*.tar.gz` release asset.
3. Generate SHA-256 from that exact uploaded asset.
4. Run `brew style --formula Formula/fresnel.rb`.
5. Run `HOMEBREW_NO_INSTALL_FROM_API=1 brew install --build-from-source Formula/fresnel.rb`.
6. Run `brew test fresnel` and `brew audit --strict --new --online Formula/fresnel.rb`.
7. Test `fresnel setup --dry-run --yes --skip-benchmark` on a clean Apple Silicon Mac.

The current formula is suitable for an experimental tap. It intentionally
downloads the pinned MLX runtime and model during `fresnel setup`, not during
`brew install`.

Fresnel's tap also carries a reviewed, commit-pinned `termtex` formula. The
Fresnel formula depends on that helper plus the official `glow` formula, so a
normal tap installation includes the complete terminal presentation stack.

## Later: homebrew/core

`homebrew/core` requires a pull request, automated CI/audit checks, and human
maintainer review. Fresnel should not target core yet. Before submitting:

- establish a public project and stable immutable releases;
- meet Homebrew's public-interest/notability expectations;
- turn all Python/MLX dependencies into immutable, checksummed build resources;
- avoid modifying the Homebrew-managed Python environment during normal use;
- document and justify Apple-Silicon-only support;
- keep the model download separate and explicit;
- provide meaningful formula tests that do not require downloading the model.

There is no guaranteed review duration for a core pull request.

## Tester archive

For direct testing, distribute the versioned `fresnel-*-macos-arm64-tester.zip` and its
adjacent `.sha256` file. Testers extract it and run `./install.sh` in Terminal.
The archive contains no model weights or credentials.
