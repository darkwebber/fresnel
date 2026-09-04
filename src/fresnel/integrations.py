"""Thin, reversible integrations for orchestrator products."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

_SOURCE_SKILL = Path(__file__).resolve().parents[2] / "integrations" / "fresnel"
_BUNDLED_SKILL = Path(__file__).resolve().parent / "_bundled_skill"
SKILL_SOURCE = _SOURCE_SKILL if _SOURCE_SKILL.is_dir() else _BUNDLED_SKILL


def destinations(product: str, project: Path | None = None) -> list[tuple[Path, str]]:
    project = (project or Path.cwd()).resolve()
    if product == "codex":
        return [(Path.home() / ".codex" / "skills" / "fresnel", "skill")]
    if product == "cursor":
        return [(project / ".cursor" / "rules" / "fresnel.mdc", "cursor")]
    if product == "opencode":
        return [(project / ".opencode" / "agents" / "fresnel.md", "generic")]
    if product == "generic":
        return [(project / "FRESNEL.md", "generic")]
    raise ValueError(f"unsupported integration: {product}")


def rendered(kind: str) -> str:
    if kind == "cursor":
        return """---
description: Delegate bounded coding components through Fresnel
alwaysApply: false
---
Use `fresnel run` or the Fresnel MCP tools for bounded local-agent work. The orchestrator owns architecture, contracts, algorithms, and final review. Inspect the returned diff and quality gates before applying it.
"""
    return """# Fresnel integration

Use Fresnel to delegate narrow implementation components to the local Spark worker.
The orchestrator owns planning, contracts, algorithms, and final review. Run
`fresnel doctor` before delegation. Treat `AWAITING_APPROVAL` as a user-visible
notification and never apply a result unless its integration quality gate passed.
"""


def install(product: str, project: Path | None = None, *, dry_run: bool = False) -> list[dict]:
    changes = []
    for destination, kind in destinations(product, project):
        changes.append(
            {"destination": str(destination), "kind": kind, "exists": destination.exists()}
        )
        if dry_run:
            continue
        if destination.exists():
            backup = destination.with_name(destination.name + f".fresnel-backup-{int(time.time())}")
            shutil.move(destination, backup)
            changes[-1]["backup"] = str(backup)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if kind == "skill":
            shutil.copytree(SKILL_SOURCE, destination)
        else:
            destination.write_text(rendered(kind))
    return changes


def uninstall(product: str, project: Path | None = None, *, dry_run: bool = False) -> list[str]:
    removed = []
    for destination, _kind in destinations(product, project):
        if not destination.exists():
            continue
        removed.append(str(destination))
        if dry_run:
            continue
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    return removed
