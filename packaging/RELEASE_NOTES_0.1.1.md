# Fresnel 0.1.1

This patch makes a successfully installed harness immediately usable.

- Adds `fresnel onboard`, a dependency-free terminal onboarding walkthrough.
- Runs onboarding automatically after interactive `fresnel setup`.
- Configures the background worker and Codex, Cursor, OpenCode, or a generic project adapter.
- Fixes Spark server discovery inside Homebrew's private Python environment.
- Adds regression coverage for the Homebrew runtime layout and onboarding paths.
- Uses Homebrew's non-interactive `--yes` option in tester installation instructions.

Existing v0.1.0 Homebrew testers should run `brew update && brew upgrade fresnel`,
then `fresnel setup`.
