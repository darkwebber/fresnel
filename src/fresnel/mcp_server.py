"""Minimal MCP stdio façade over the canonical Fresnel CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from . import __version__

TOOLS = [
    (
        "fresnel_plan",
        "Ask the configured coordinator to produce a versioned Fresnel plan",
        ["repo", "request"],
    ),
    ("fresnel_run", "Run a reviewed plan in a disposable workspace", ["repo", "plan"]),
    ("fresnel_status", "Read recent Fresnel run state", []),
    ("fresnel_approve", "Record a user approval decision", ["request_id", "decision"]),
    ("fresnel_review", "Read a Fresnel review packet", ["path"]),
    ("fresnel_apply", "Run and apply a validated plan", ["repo", "plan"]),
    ("fresnel_benchmark", "Run Mac-aware worker calibration", []),
    ("fresnel_contract", "Read the current versioned orchestrator contract", []),
]


def definitions() -> list[dict[str, Any]]:
    result = []
    for name, description, required in TOOLS:
        properties = {field: {"type": "string"} for field in required}
        if name == "fresnel_approve":
            properties["decision"] = {"type": "string", "enum": ["approve", "deny"]}
        result.append(
            {
                "name": name,
                "description": description,
                "inputSchema": {"type": "object", "properties": properties, "required": required},
            }
        )
    return result


def command(name: str, arguments: dict[str, Any]) -> list[str]:
    if name == "fresnel_plan":
        return ["fresnel", "plan", "--repo", arguments["repo"], "--request", arguments["request"]]
    if name in {"fresnel_run", "fresnel_apply"}:
        result = ["fresnel", "run", "--repo", arguments["repo"], "--plan", arguments["plan"]]
        return result + (["--apply"] if name == "fresnel_apply" else [])
    if name == "fresnel_status":
        return ["fresnel", "status", "--json"]
    if name == "fresnel_approve":
        return ["fresnel", "approve", arguments["request_id"], arguments["decision"]]
    if name == "fresnel_review":
        return ["fresnel", "review", arguments["path"]]
    if name == "fresnel_benchmark":
        return ["fresnel", "benchmark", "--json"]
    if name == "fresnel_contract":
        return ["fresnel", "contract", "--format", "json"]
    raise ValueError(f"unknown MCP tool: {name}")


def response(identifier: Any, result: Any = None, error: str | None = None) -> dict:
    message = {"jsonrpc": "2.0", "id": identifier}
    if error:
        message["error"] = {"code": -32000, "message": error}
    else:
        message["result"] = result
    return message


def serve() -> None:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            method = request.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fresnel", "version": __version__},
                }
            elif method == "tools/list":
                result = {"tools": definitions()}
            elif method == "tools/call":
                params = request.get("params", {})
                completed = subprocess.run(
                    command(params["name"], params.get("arguments", {})),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                result = {
                    "content": [{"type": "text", "text": completed.stdout}],
                    "isError": completed.returncode != 0,
                }
            elif method == "notifications/initialized":
                continue
            else:
                raise ValueError(f"unsupported method: {method}")
            print(json.dumps(response(request.get("id"), result)), flush=True)
        except Exception as exc:
            print(json.dumps(response(None, error=f"{type(exc).__name__}: {exc}")), flush=True)
