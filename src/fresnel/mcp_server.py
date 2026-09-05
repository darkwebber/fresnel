"""Minimal MCP stdio façade over the canonical Fresnel CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import Any

from . import __version__

TOOLS = [
    (
        "fresnel_plan",
        "Ask the configured coordinator to produce a versioned Fresnel plan",
        ["repo", "request"],
    ),
    ("fresnel_run", "Run a reviewed plan in a durable, recoverable workspace", ["repo", "plan"]),
    ("fresnel_resume", "Resume a task from its last verified checkpoint", ["run_id"]),
    ("fresnel_cancel", "Request checkpointed cancellation of a running task", ["run_id"]),
    ("fresnel_status", "Read recent Fresnel run state", []),
    ("fresnel_approve", "Record a user approval decision", ["request_id", "decision"]),
    ("fresnel_review", "Read a Fresnel review packet", ["path"]),
    ("fresnel_apply", "Run and apply a validated plan", ["repo", "plan"]),
    ("fresnel_benchmark", "Run Mac-aware worker calibration", []),
    ("fresnel_contract", "Read the current versioned orchestrator contract", []),
    ("fresnel_capabilities", "Discover local worker capabilities for an intent", ["intent"]),
    ("fresnel_memory_profile", "Read local user and project memory", ["repo"]),
]


def definitions() -> list[dict[str, Any]]:
    result = []
    for name, description, required in TOOLS:
        properties = {field: {"type": "string"} for field in required}
        if name == "fresnel_status":
            properties.update(
                {
                    "run_id": {"type": "string"},
                    "follow": {"type": "boolean", "default": False},
                }
            )
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
    if name == "fresnel_resume":
        return ["fresnel", "run", "--resume", arguments["run_id"]]
    if name == "fresnel_cancel":
        return ["fresnel", "cancel", arguments["run_id"]]
    if name == "fresnel_status":
        result = ["fresnel", "status", "--json"]
        if arguments.get("run_id"):
            result.extend(["--run", arguments["run_id"]])
        if arguments.get("follow"):
            result.append("--follow")
        return result
    if name == "fresnel_approve":
        return ["fresnel", "approve", arguments["request_id"], arguments["decision"]]
    if name == "fresnel_review":
        return ["fresnel", "review", arguments["path"]]
    if name == "fresnel_benchmark":
        return ["fresnel", "benchmark", "--json"]
    if name == "fresnel_contract":
        return ["fresnel", "contract", "--format", "json"]
    if name == "fresnel_capabilities":
        return ["fresnel", "capabilities", arguments["intent"]]
    if name == "fresnel_memory_profile":
        return ["fresnel", "memory", "profile", "--repo", arguments["repo"]]
    raise ValueError(f"unknown MCP tool: {name}")


def response(identifier: Any, result: Any = None, error: str | None = None) -> dict:
    message = {"jsonrpc": "2.0", "id": identifier}
    if error:
        message["error"] = {"code": -32000, "message": error}
    else:
        message["result"] = result
    return message


def _send(message: dict[str, Any]) -> None:
    print(json.dumps(message), flush=True)


def _progress_notification(event: dict[str, Any], token: Any = None) -> dict[str, Any]:
    eta = event.get("eta_seconds")
    eta_text = " · ETA estimating" if eta is None else f" · ETA {eta}s"
    message = f"{event.get('label', 'Fresnel is working')}{eta_text}"
    if token is not None:
        return {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {
                "progressToken": token,
                "progress": event.get("progress", 0),
                "total": max(1, event.get("total", 1)),
                "message": message,
            },
        }
    return {
        "jsonrpc": "2.0",
        "method": "notifications/message",
        "params": {"level": "info", "logger": "fresnel", "data": message},
    }


def execute_tool(command_line: list[str], progress_token: Any = None) -> tuple[str, int]:
    """Run a CLI tool while translating stderr events into MCP progress notifications."""
    environment = {**os.environ, "FRESNEL_PROGRESS": "json"}
    process = subprocess.Popen(
        command_line,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    diagnostics: list[str] = []

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            if line.startswith("FRESNEL_PROGRESS "):
                try:
                    event = json.loads(line.removeprefix("FRESNEL_PROGRESS "))
                    _send(_progress_notification(event, progress_token))
                except json.JSONDecodeError:
                    diagnostics.append(line)
            else:
                diagnostics.append(line)

    reader = threading.Thread(target=read_stderr, daemon=True)
    reader.start()
    assert process.stdout is not None
    output = process.stdout.read()
    return_code = process.wait()
    reader.join(timeout=2)
    return output + "".join(diagnostics), return_code


def serve() -> None:
    print(
        "Fresnel MCP ready \u00b7 waiting for orchestrator requests over stdio \u00b7 looks idle? see docs/workflows.md",
        file=sys.stderr,
        flush=True,
    )
    for line in sys.stdin:
        request: dict[str, Any] | None = None
        try:
            request = json.loads(line)
            method = request.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}, "logging": {}},
                    "serverInfo": {"name": "fresnel", "version": __version__},
                    "instructions": (
                        "Fresnel delegates bounded implementation to local Spark. Tool calls emit "
                        "live phase, component, retry, validation, ETA, and completion progress."
                    ),
                }
            elif method == "tools/list":
                result = {"tools": definitions()}
            elif method == "tools/call":
                params = request.get("params", {})
                progress_token = params.get("_meta", {}).get("progressToken")
                output, return_code = execute_tool(
                    command(params["name"], params.get("arguments", {})),
                    progress_token,
                )
                result = {
                    "content": [{"type": "text", "text": output}],
                    "isError": return_code != 0,
                }
            elif method == "notifications/initialized":
                continue
            else:
                raise ValueError(f"unsupported method: {method}")
            _send(response(request.get("id"), result))
        except Exception as exc:
            identifier = request.get("id") if isinstance(request, dict) else None
            _send(response(identifier, error=f"{type(exc).__name__}: {exc}"))
