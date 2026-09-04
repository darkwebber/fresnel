"""Fresnel protocol-v1 validation types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import PROTOCOL_VERSION


@dataclass(frozen=True)
class RiskEnvelope:
    write_paths: tuple[str, ...] = ()
    network: str = "none"
    installs: bool = False
    external_writes: bool = False


@dataclass(frozen=True)
class ResourceBudgets:
    max_capability_calls: int = 8
    max_edit_attempts: int = 3
    wall_seconds: int = 300


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
    interfaces: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    risk: RiskEnvelope = field(default_factory=RiskEnvelope)
    budgets: ResourceBudgets = field(default_factory=ResourceBudgets)


@dataclass(frozen=True)
class Plan:
    objective: str
    components: tuple[Component, ...]
    scope: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    contracts: tuple[Contract, ...] = ()
    integration_validation: tuple[tuple[str, ...], ...] = ()
    review_checklist: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
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
    if version not in {"1.0", "1.1"}:
        raise ValueError(f"unsupported protocol version: {version}")
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
        risk = item.get("risk_envelope", {})
        budgets = item.get("budgets", {})
        write_paths = _paths(risk.get("write_paths", list(targets)), "risk_envelope.write_paths")
        if set(write_paths) - set(targets):
            raise ValueError("risk envelope may write only declared targets")
        if version == "1.1" and set(write_paths) != set(targets):
            raise ValueError("protocol 1.1 risk envelope must authorize every declared target")
        network = str(
            risk.get("network", "reference-only" if refs.get("allow_worker_web") else "none")
        )
        if network not in {"none", "reference-only"}:
            raise ValueError("risk_envelope.network must be none or reference-only")
        component = Component(
            id=component_id,
            task=str(item.get("task", "")),
            targets=targets,
            context=_paths(item.get("context", []), "context"),
            constraints=_strings(item.get("constraints", []), "constraints"),
            interfaces=_strings(item.get("interfaces", []), "interfaces"),
            invariants=_strings(item.get("invariants", []), "invariants"),
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
            risk=RiskEnvelope(
                write_paths=write_paths,
                network=network,
                installs=bool(risk.get("installs", False)),
                external_writes=bool(risk.get("external_writes", False)),
            ),
            budgets=ResourceBudgets(
                max_capability_calls=max(
                    0, min(32, int(budgets.get("max_capability_calls", 8)))
                ),
                max_edit_attempts=max(1, min(10, int(budgets.get("max_edit_attempts", 3)))),
                wall_seconds=max(30, min(3600, int(budgets.get("wall_seconds", 300)))),
            ),
        )
        components.append(component)
        completed.add(component_id)
        all_targets.update(targets)
    if not components:
        raise ValueError("plan must contain at least one component")
    default_scope = list(dict.fromkeys(path for component in components for path in component.targets))
    default_acceptance = list(
        dict.fromkeys(item for component in components for item in component.acceptance)
    )
    default_constraints = list(
        dict.fromkeys(item for component in components for item in component.constraints)
    )
    return Plan(
        objective=str(raw.get("objective", "")),
        scope=_paths(raw.get("scope", default_scope), "scope", allow_empty=False),
        acceptance=_strings(
            raw.get("acceptance", default_acceptance), "plan acceptance", allow_empty=False
        ),
        constraints=_strings(raw.get("constraints", default_constraints), "plan constraints"),
        contracts=contracts,
        components=tuple(components),
        integration_validation=_commands(
            raw.get("integration_validation", []), "integration_validation"
        ),
        review_checklist=_strings(raw.get("review_checklist", []), "review_checklist"),
        interfaces=_strings(raw.get("interfaces", []), "interfaces"),
        invariants=_strings(raw.get("invariants", []), "invariants"),
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


def contract_schema() -> dict[str, Any]:
    """Canonical tool-neutral protocol description consumed by every adapter."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "compatible_plan_versions": ["1.0", "1.1"],
        "task_charter": {
            "required": ["objective", "scope", "acceptance", "constraints"],
            "optional": ["interfaces", "invariants", "review_checklist"],
            "immutable": True,
        },
        "component_envelope": {
            "required": ["id", "task", "targets", "acceptance", "implementation", "validation"],
            "optional": [
                "depends_on",
                "context",
                "constraints",
                "interfaces",
                "invariants",
                "risk_envelope",
                "budgets",
            ],
        },
        "worker_operations": [
            "EDIT",
            "CREATE",
            "NEEDS_CAPABILITY",
            "NEEDS_REFERENCE",
            "REQUEST_ACTION",
        ],
        "capability_request": {
            "required": ["capability", "intent"],
            "discovery_capability": "discover",
        },
        "capability_result": [
            "id",
            "capability",
            "intent",
            "source",
            "content",
            "source_hash",
            "fresh_at",
            "continuation",
        ],
        "checkpoint": ["run_id", "component_id", "sequence", "state", "hashes", "report"],
        "result_packet": [
            "run_id",
            "status",
            "diff",
            "components",
            "integration_validation",
            "metrics",
            "progress",
            "memory",
        ],
    }
