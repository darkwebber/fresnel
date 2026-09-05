"""macOS command confinement and secret-minimizing execution environment."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def clean_environment(root: Path | None = None) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "TERM", "TMPDIR", "NO_COLOR")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    private = (root or Path("/private/tmp/fresnel-sandbox")).resolve() / ".fresnel-runtime"
    private.mkdir(parents=True, mode=0o700, exist_ok=True)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["HOME"] = str(private)
    environment["TMPDIR"] = str(private)
    return environment


def command(root: Path, argv: tuple[str, ...]) -> list[str]:
    sandbox = Path("/usr/bin/sandbox-exec")
    if platform.system() != "Darwin" or not sandbox.is_file():
        return list(argv)
    resolved_root = root.resolve()
    escaped_root = str(resolved_root).replace("\\", "\\\\").replace('"', '\\"')
    home = Path.home().resolve()
    sensitive = (
        home / ".ssh",
        home / ".aws",
        home / ".config" / "gcloud",
        home / "Library" / "Keychains",
        home / "Library" / "Application Support" / "Fresnel",
    )
    denied_reads = ""
    for path in sensitive:
        escaped_sensitive = str(path).replace('"', '\\"')
        # Durable run workspaces intentionally live below Application
        # Support/Fresnel. Permit file data only inside the active workspace.
        denied_reads += (
            f'(deny file-read-data (require-all (subpath "{escaped_sensitive}") '
            f'(require-not (subpath "{escaped_root}"))))'
        )

        # Runtime loaders realpath() every parent of cwd. Permit metadata for
        # that exact traversal chain, while retaining the deny for sibling state.
        traversal = [resolved_root]
        traversal.extend(
            parent
            for parent in resolved_root.parents
            if parent == path or path in parent.parents
        )
        allowed_metadata = " ".join(
            f'(literal "{str(item).replace(chr(34), chr(92) + chr(34))}")'
            for item in traversal
        )
        denied_reads += (
            f'(deny file-read-metadata '
            f'(require-all (subpath "{escaped_sensitive}") '
            f'(require-not (require-any (subpath "{escaped_root}") '
            f'{allowed_metadata}))))'
        )
    profile = (
        "(version 1)(allow default)(deny network*)"
        f'(deny file-write* (require-not (subpath "{escaped_root}")))'
        + denied_reads
    )
    return [str(sandbox), "-p", profile, *argv]
