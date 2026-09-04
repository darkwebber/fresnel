"""Deterministic approval classification and stable notification IDs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

POLICY_VERSION = "v1"


def request_id(component: str, request: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"component": component, "request": request}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def classify(request: dict[str, Any], *, web_authorized: bool = False) -> tuple[str, str]:
    kind = request.get("kind")
    if kind in {"local_docs", "file_excerpt"}:
        return "approve", "local read-only documentation"
    if kind == "exa":
        if web_authorized and request.get("include_domains"):
            return "approve", "authorized domain-restricted reference search"
        return "escalate", "external search is unplanned or unrestricted"
    if kind == "help_command":
        argv = request.get("argv") or []
        if argv and any(arg in {"--help", "-h", "help"} for arg in argv[1:]):
            return "approve", "local CLI help"
        return "deny", "not a constrained help request"
    if kind == "run_command":
        argv = request.get("argv") or []
        executable = Path(str(argv[0])).name if argv else ""
        if executable in {"rg", "grep", "ls", "pwd", "head", "tail", "wc"}:
            return "approve", "read-only diagnostic in disposable workspace"
        if executable == "git" and len(argv) > 1 and argv[1] in {"diff", "status", "log", "show"}:
            return "approve", "read-only git inspection"
        return "escalate", "unplanned command may execute code or change state"
    if kind in {"read_secret", "path_escape", "modify_contract", "write_outside_targets"}:
        return "deny", "violates the worker isolation boundary"
    if kind in {
        "install_dependency",
        "delete_file",
        "deploy",
        "push",
        "external_write",
        "apply_real_repo",
    }:
        return "escalate", "consequential or externally visible action"
    return "escalate", "unknown action type"


def decide(
    component: str,
    request: dict[str, Any],
    decisions: dict[str, str],
    *,
    web_authorized: bool = False,
) -> dict[str, Any]:
    identifier = request_id(component, request)
    policy_decision, reason = classify(request, web_authorized=web_authorized)
    override = decisions.get(identifier)
    if policy_decision == "deny":
        decision = "deny"
    elif override in {"approve", "approved"}:
        decision, reason = "approve", "explicitly approved by user"
    elif override in {"deny", "denied"}:
        decision, reason = "deny", "explicitly denied by user"
    else:
        decision = policy_decision
    return {
        "protocol_version": "1.0",
        "id": identifier,
        "component_id": component,
        "decision": decision,
        "policy_decision": policy_decision,
        "reason": reason,
        "request": request,
    }
