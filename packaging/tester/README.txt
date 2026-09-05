FRESNEL 0.5.1 — APPLE SILICON TESTER BUILD

Requirements
------------
- Apple Silicon Mac
- macOS 14 or newer
- At least 16 GB unified memory
- Homebrew
- Internet access during setup
- Approximately 5 GB free disk space for the pinned model and runtime

Install
-------
1. Extract this archive.
2. Open Terminal in the extracted directory.
3. Run:

       ./install.sh

The script verifies the included wheel, installs Fresnel in an isolated Python
environment without compiling dependencies, and launches guided setup. Setup downloads the revision-pinned
Spark-X2.5-4B MLX 8-bit model (approximately 4.1 GB) from Hugging Face and runs
an adaptive hardware calibration. It then opens an onboarding walkthrough for
the background worker and your preferred coding orchestrator.

The native helpers are ad-hoc signed for integrity but this is not a notarized
Apple .pkg application. If
macOS quarantines the downloaded archive, open Terminal and invoke install.sh
from there rather than bypassing Gatekeeper for an unknown binary.

Verify
------

       fresnel doctor --json
       fresnel --version

Integrations
------------

       fresnel integrations install codex
       fresnel integrations install cursor --project /path/to/project
       fresnel integrations install opencode --project /path/to/project

Ask, sessions, and memory
-------------------------

       fresnel ask "Explain this PySpark failure"
       fresnel ask --session investigation "Analyze this stack trace"
       fresnel ask --session investigation --resume
       fresnel memory status

Interactive completed answers are rendered with Glow and copied to the macOS
clipboard as raw Markdown. Pipes and JSON output are never copied.

Uninstall
---------

       fresnel uninstall
       fresnel uninstall

Model files are preserved by default so an uninstall does not unexpectedly
delete a multi-gigabyte download.
