"""Fresnel protocol-v1 validation types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import PROTOCOL_VERSION


@dataclass(frozen=True)
class References:
    local_docs: tuple[str, ...] = ()
    help_commands: tuple[tuple[str, ...], ...] = ()
    web_queries: tuple[dict[str, Any], ...] = ()
    allow_worker_web: bool = False


@dataclass(frozen=True)
class Contract:
    path: str
    content: str


@dataclass(frozen=True)
class Component:
    id: str
    task: str
    targets: tuple[str, ...]
    acceptance: tuple[str, ...]
    implementation: tuple[str, ...]
    validation: tuple[tuple[str, ...], ...]
    depends_on: tuple[str, ...] = ()
    context: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    references: References = field(default_factory=References)


@dataclass(frozen=True)
class Plan:
    objective: str
    components: tuple[Component, ...]
    contracts: tuple[Contract, ...] = ()
    integration_validation: tuple[tuple[str, ...], ...] = ()
    review_checklist: tuple[str, ...] = ()
    protocol_version: str = PROTOCOL_VERSION


def _strings(values: Any, field_name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    if not allow_empty and not values:
        raise ValueError(f"{field_name} cannot be empty")
    return tuple(values)


def _commands(values: Any, field_name: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list")
    commands = []
    for command in values:
        commands.append(_strings(command, field_name, allow_empty=False))
    return tuple(commands)


def _paths(values: Any, field_name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    paths = _strings(values, field_name, allow_empty=allow_empty)
    for value in paths:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value in {".", ""}:
            raise ValueError(f"{field_name} must contain repository-relative paths")
    return paths


def parse_plan(raw: dict[str, Any]) -> Plan:
    version = str(raw.get("protocol_version", PROTOCOL_VERSION))
    if version.split(".", 1)[0] != PROTOCOL_VERSION.split(".", 1)[0]:
        raise ValueError(f"unsupported protocol major version: {version}")
    contracts = tuple(
        Contract(path=str(item["path"]), content=str(item["content"]))
        for item in raw.get("contracts", [])
    )
    contract_paths = [item.path for item in contracts]
    _paths(contract_paths, "contract paths")
    if len(contract_paths) != len(set(contract_paths)):
        raise ValueError("contract paths must be unique")
    components = []
    completed: set[str] = set()
    all_targets: set[str] = set()
    for item in raw.get("components", []):
        component_id = str(item.get("id", ""))
        if not component_id or component_id in completed:
            raise ValueError("component ids must be non-empty and unique")
        dependencies = _strings(item.get("depends_on", []), "depends_on")
        missing = set(dependencies) - completed
        if missing:
            raise ValueError(
                f"component {component_id} has unsatisfied dependencies: {sorted(missing)}"
            )
        targets = _paths(item.get("targets", []), "targets", allow_empty=False)
        if set(targets).intersection(contract_paths):
            raise ValueError("workers cannot edit coordinator contracts")
        refs = item.get("references", {})
        component = Component(
            id=component_id,
            task=str(item.get("task", "")),
            targets=targets,
            context=_paths(item.get("context", []), "context"),
            constraints=_strings(item.get("constraints", []), "constraints"),
            acceptance=_strings(item.get("acceptance", []), "acceptance", allow_empty=False),
            implementation=_strings(
                item.get("implementation", []), "implementation", allow_empty=False
            ),
            validation=_commands(item.get("validation", []), "validation"),
            depends_on=dependencies,
            references=References(
                local_docs=_strings(refs.get("local_docs", []), "local_docs"),
                help_commands=_commands(refs.get("help_commands", []), "help_commands"),
                web_queries=tuple(refs.get("web_queries", [])),
                allow_worker_web=bool(refs.get("allow_worker_web", False)),
            ),
        )
        components.append(component)
        completed.add(component_id)
        all_targets.update(targets)
    if not components:
        raise ValueError("plan must contain at least one component")
    return Plan(
        objective=str(raw.get("objective", "")),
        contracts=contracts,
        components=tuple(components),
        integration_validation=_commands(
            raw.get("integration_validation", []), "integration_validation"
        ),
        review_checklist=_strings(raw.get("review_checklist", []), "review_checklist"),
        protocol_version=version,
    )


def safe_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    supplied = Path(relative)
    if supplied.is_absolute():
        raise ValueError("absolute paths are forbidden")
    unresolved = root / supplied
    if unresolved.is_symlink():
        raise ValueError("symlink targets are forbidden")
    resolved = unresolved.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("path escapes repository")
    return resolved
