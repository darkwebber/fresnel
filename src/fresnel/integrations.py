"""Versioned, reversible orchestrator contracts and product adapters."""

from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

from . import PROTOCOL_VERSION, __version__
from .protocol import contract_schema
from .store import Store

CONTRACT_VERSION = __version__
_SOURCE_SKILL = Path(__file__).resolve().parents[2] / "integrations" / "fresnel"
_BUNDLED_SKILL = Path(__file__).resolve().parent / "_bundled_skill"
SKILL_SOURCE = _SOURCE_SKILL if _SOURCE_SKILL.is_dir() else _BUNDLED_SKILL


def contract_data() -> dict[str, Any]:
    return {
        "fresnel_version": __version__,
        "contract_version": CONTRACT_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "schema": contract_schema(),
        "role": "The external orchestrator is the architect, taste-maker, approval controller, and final reviewer; Spark is a bounded implementation worker.",
        "workflow": [
            "Inspect the repository and convert the user goal into an ordered protocol plan.",
            "Keep architecture, algorithms, interfaces, contracts, acceptance criteria, and integration tests under orchestrator control.",
            "Delegate only narrow components with explicit targets, context, implementation details, and validation commands.",
            "Estimate output size before delegation; split large modules into bounded functions or files. Supply exact interfaces and only relevant test excerpts. Avoid broad framework manuals.",
            "After two failures with the same cause, inspect raw output and replan the component or fix infrastructure before retrying. Keep failed reports; distinguish worker code, harness, and orchestrator failures.",
            "The harness validates returned edits automatically. Do not ask the worker to request validation before producing missing files. Never provide a full implementation merely to have the worker echo it.",
            "Resolve local documentation first and use domain-restricted Exa only when the plan authorizes web research.",
            "Run Fresnel in its durable workspace, inspect validation evidence and diff, and apply only after semantic review.",
            "Surface AWAITING_APPROVAL to the user; never infer approval for destructive or externally visible actions.",
            "Use Fresnel memory replay after interruption and report quality, token, latency, cache, and retry metrics.",
            "Relay MCP progress notifications or CLI JSON progress to the user, including phase, component, attempt, completed/total, ETA, retries, and validation state.",
        ],
        "commands": {
            "health": "fresnel doctor --json",
            "plan": "fresnel plan --repo REPO --request REQUEST --output PLAN.json",
            "run": "fresnel run --repo REPO --plan PLAN.json --output REPORT.json --progress json",
            "review": "fresnel review REPORT.json",
            "apply": "fresnel run --resume RUN_ID --apply",
            "contract": "fresnel contract --format json",
            "memory": "fresnel memory inspect --run RUN_ID",
            "resume": "fresnel run --resume RUN_ID",
            "follow": "fresnel status --run RUN_ID --follow",
            "cancel": "fresnel cancel RUN_ID",
            "capabilities": "fresnel capabilities INTENT",
        },
        "worker_contract": {
            "allowed": [
                "EDIT",
                "CREATE",
                "NEEDS_CAPABILITY",
                "NEEDS_REFERENCE",
                "REQUEST_ACTION",
            ],
            "never": [
                "redesign architecture",
                "edit undeclared targets",
                "edit coordinator contracts",
                "receive secrets",
                "apply an unvalidated or truncated response",
            ],
        },
    }


def contract_markdown() -> str:
    data = contract_data()
    workflow = "\n".join(f"{number}. {step}" for number, step in enumerate(data["workflow"], 1))
    commands = "\n".join(f"- `{name}`: `{command}`" for name, command in data["commands"].items())
    forbidden = "\n".join(f"- {item}" for item in data["worker_contract"]["never"])
    return f"""# Fresnel orchestrator contract

Contract version: {CONTRACT_VERSION}
Protocol version: {PROTOCOL_VERSION}

{data['role']}

## Required workflow

{workflow}

## Delegation contract

Create small components with stable IDs and only earlier dependencies. Every component must
declare repository-relative targets, optional read-only context, constraints, acceptance checks,
required implementation details, validation argv arrays, and authorized references. Prefer MCP
tools when available; the CLI is the portable contract. A local worker response is untrusted until
Fresnel has parsed it, applied it in a durable workspace, and passed component and integration
validation. The orchestrator must still review the complete diff for semantic correctness.

Never let Spark:

{forbidden}

## Approvals and references

Approve bounded local reads, declared edits, validation, local help, and plan-authorized,
domain-restricted Exa lookup. Deny secret access, path escape, and contract modification. Escalate
installs, deletion, deployment, pushing, external writes, and ambiguous actions to the user.

## Memory and recovery

Fresnel owns durable project memory. After interruption, inspect or replay the run instead of
asking Spark to remember prior chat. Treat the task charter, event-derived situation state, Git
diff, and validation evidence as authoritative. Do not paste complete logs or repository contents
into Spark; declare context and let Fresnel retrieve exact evidence.

## Commands

{commands}

When reporting results, include validation outcome, whether changes were applied, coordinator and
worker tokens, cache hits, retries, reference reads, latency, and any pending approval.
During a long call, relay Fresnel progress rather than leaving the user with an apparently idle
agent. MCP progress notifications are preferred; CLI integrations consume `--progress json` from
stderr without mixing it into the final JSON report.
"""


def destinations(product: str, project: Path | None = None) -> list[tuple[Path, str]]:
    project = (project or Path.cwd()).resolve()
    if product == "codex":
        return [(Path.home() / ".codex" / "skills" / "fresnel", "skill")]
    if product == "cursor":
        return [(project / ".cursor" / "rules" / "fresnel.mdc", "cursor")]
    if product == "opencode":
        return [(project / ".opencode" / "skills" / "fresnel", "skill")]
    if product == "generic":
        return [(project / "FRESNEL.md", "generic")]
    raise ValueError(f"unsupported integration: {product}")


def rendered(kind: str) -> str:
    body = contract_markdown()
    if kind == "cursor":
        return f"""---
description: Use Fresnel for cost-efficient local implementation while the current agent retains architecture, planning, approvals, and final review
alwaysApply: false
---
{body}
"""
    return body


def _expected(kind: str) -> dict[str, bytes]:
    if kind != "skill":
        return {"": rendered(kind).encode()}
    return {
        str(source.relative_to(SKILL_SOURCE)): source.read_bytes()
        for source in sorted(SKILL_SOURCE.rglob("*"))
        if source.is_file()
    }


def _checksum_files(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative, content in sorted(files.items()):
        digest.update(relative.encode() + b"\0" + content + b"\0")
    return digest.hexdigest()


def _checksum_path(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_file():
        return _checksum_files({"": path.read_bytes()})
    return _checksum_files(
        {
            str(item.relative_to(path)): item.read_bytes()
            for item in path.rglob("*")
            if item.is_file()
        }
    )


def _write_expected(destination: Path, kind: str) -> None:
    files = _expected(kind)
    if kind == "skill":
        destination.mkdir(parents=True, exist_ok=True)
        for relative, content in files.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(files[""])


def _registration_root(product: str, project: Path | None) -> str:
    return "__global__" if product == "codex" else str((project or Path.cwd()).resolve())


def _register(store: Store, product: str, project: Path | None, destination: Path, checksum: str):
    store.connection.execute(
        "INSERT INTO integration_installs VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(product, project_root, destination) DO UPDATE SET version=excluded.version, "
        "checksum=excluded.checksum, updated_at=excluded.updated_at",
        (
            product,
            _registration_root(product, project),
            str(destination),
            CONTRACT_VERSION,
            checksum,
            time.time(),
        ),
    )
    store.connection.commit()


def install(
    product: str,
    project: Path | None = None,
    *,
    dry_run: bool = False,
    store: Store | None = None,
) -> list[dict]:
    owned_store = store is None
    store = store or Store()
    changes = []
    for destination, kind in destinations(product, project):
        expected_checksum = _checksum_files(_expected(kind))
        change = {
            "destination": str(destination),
            "kind": kind,
            "exists": destination.exists(),
            "version": CONTRACT_VERSION,
            "checksum": expected_checksum,
        }
        changes.append(change)
        if dry_run:
            continue
        if destination.exists() and _checksum_path(destination) != expected_checksum:
            backup = destination.with_name(destination.name + f".fresnel-backup-{int(time.time())}")
            shutil.move(destination, backup)
            change["backup"] = str(backup)
        elif destination.exists():
            shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
        _write_expected(destination, kind)
        _register(store, product, project, destination, expected_checksum)
    if product == "opencode":
        legacy = (project or Path.cwd()).resolve() / ".opencode" / "agents" / "fresnel.md"
        if legacy.exists():
            migration = {"legacy": str(legacy), "action": "would-back-up" if dry_run else "backed-up"}
            if not dry_run:
                backup = legacy.with_name(legacy.name + f".fresnel-backup-{int(time.time())}")
                shutil.move(legacy, backup)
                migration["backup"] = str(backup)
            changes.append(migration)
    if owned_store:
        store.close()
    return changes


def status(
    product: str | None = None,
    project: Path | None = None,
    *,
    store: Store | None = None,
) -> list[dict[str, Any]]:
    owned_store = store is None
    store = store or Store()
    clauses, params = [], []
    if product:
        clauses.append("product=?")
        params.append(product)
    if project or (product and product != "codex"):
        clauses.append("project_root=?")
        params.append(_registration_root(product or "generic", project))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = store.connection.execute(
        "SELECT * FROM integration_installs" + where + " ORDER BY product, destination",
        params,
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        destination = Path(item["destination"])
        registered_project = (
            None if item["project_root"] == "__global__" else Path(item["project_root"])
        )
        kind = destinations(item["product"], registered_project)[0][1]
        expected = _checksum_files(_expected(kind))
        current = _checksum_path(destination)
        if current is None:
            state = "missing"
        elif current != item["checksum"]:
            state = "modified"
        elif item["version"] != CONTRACT_VERSION or current != expected:
            state = "stale"
        else:
            state = "current"
        result.append({**item, "state": state, "current_checksum": current})
    if owned_store:
        store.close()
    return result


def sync(
    product: str | None = None,
    project: Path | None = None,
    *,
    dry_run: bool = False,
    store: Store | None = None,
) -> list[dict[str, Any]]:
    owned_store = store is None
    store = store or Store()
    results = []
    for item in status(product, project, store=store):
        destination = Path(item["destination"])
        registered_project = (
            None if item["project_root"] == "__global__" else Path(item["project_root"])
        )
        kind = destinations(item["product"], registered_project)[0][1]
        expected_checksum = _checksum_files(_expected(kind))
        if item["state"] == "modified":
            results.append(
                {**item, "action": "preserved", "expected_checksum": expected_checksum}
            )
            continue
        action = "unchanged" if item["state"] == "current" else "updated"
        if not dry_run and action == "updated":
            if destination.is_dir():
                shutil.rmtree(destination)
            elif destination.exists():
                destination.unlink()
            _write_expected(destination, kind)
            _register(store, item["product"], registered_project, destination, expected_checksum)
        results.append({**item, "action": action, "expected_checksum": expected_checksum})
    if owned_store:
        store.close()
    return results


def diff(product: str, project: Path | None = None) -> str:
    destination, kind = destinations(product, project)[0]
    if kind == "skill":
        target = destination / "SKILL.md"
        current = target.read_text() if target.exists() else ""
        expected = _expected(kind).get("SKILL.md", b"").decode()
    else:
        current = destination.read_text() if destination.exists() else ""
        expected = rendered(kind)
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=str(destination),
            tofile=f"Fresnel {CONTRACT_VERSION}",
        )
    )


def repair(
    product: str,
    project: Path | None = None,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict]:
    destination, kind = destinations(product, project)[0]
    expected_checksum = _checksum_files(_expected(kind))
    current = _checksum_path(destination)
    if current and current != expected_checksum and not force:
        raise ValueError("integration is modified; inspect diff or use repair --force")
    return install(product, project, dry_run=dry_run)


def uninstall(
    product: str,
    project: Path | None = None,
    *,
    dry_run: bool = False,
    store: Store | None = None,
) -> list[str]:
    owned_store = store is None
    store = store or Store()
    removed = []
    root = _registration_root(product, project)
    for destination, _kind in destinations(product, project):
        if destination.exists():
            removed.append(str(destination))
            if not dry_run:
                shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
        if not dry_run:
            store.connection.execute(
                "DELETE FROM integration_installs WHERE product=? AND project_root=? "
                "AND destination=?",
                (product, root, str(destination)),
            )
    if not dry_run:
        store.connection.commit()
    if owned_store:
        store.close()
    return removed


def auto_sync() -> list[dict[str, Any]]:
    return sync()


def contract_json() -> str:
    return json.dumps(contract_data(), indent=2) + "\n"
