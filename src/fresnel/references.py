"""Local-first documentation and bounded Exa retrieval."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from .protocol import safe_path
from .sandbox import clean_environment
from .sandbox import command as sandbox_command


def pydoc_reference(symbol: str, python: str | None = None, timeout: int = 20) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", symbol):
        raise ValueError("pydoc symbol must be a dotted Python identifier")
    python = python or sys.executable
    root = Path("/private/tmp/fresnel-docs")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    started = time.perf_counter()
    completed = subprocess.run(
        sandbox_command(root, (python, "-m", "pydoc", symbol)),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env=clean_environment(root),
        check=False,
    )
    return {
        "kind": "local_docs",
        "query": symbol,
        "exit_code": completed.returncode,
        "content": completed.stdout[-8000:],
        "seconds": round(time.perf_counter() - started, 3),
    }


def help_reference(argv: list[str], cwd: Path, timeout: int = 20) -> dict[str, Any]:
    if not argv or not any(arg in {"--help", "-h", "help"} for arg in argv[1:]):
        raise ValueError("help command must contain --help, -h, or help")
    if any(arg in {"-c", "-m", "--eval"} for arg in argv):
        raise ValueError("executable code flags are forbidden in help commands")
    started = time.perf_counter()
    completed = subprocess.run(
        sandbox_command(cwd, tuple(argv)),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env=clean_environment(cwd),
        check=False,
    )
    return {
        "kind": "help_command",
        "query": argv,
        "exit_code": completed.returncode,
        "content": completed.stdout[-8000:],
        "seconds": round(time.perf_counter() - started, 3),
    }


def exa_reference(
    query: str,
    api_key: str,
    include_domains: list[str],
    *,
    timeout: int = 30,
    max_characters: int = 2500,
) -> dict[str, Any]:
    if not include_domains:
        raise ValueError("Exa references require at least one allowed domain")
    payload = {
        "query": query,
        "type": "fast",
        "numResults": 3,
        "includeDomains": include_domains,
        "systemPrompt": "Prefer current official primary documentation.",
        "contents": {"highlights": {"query": query, "maxCharacters": max_characters}},
    }
    request = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-api-key": api_key},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    results = [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "highlights": item.get("highlights", []),
        }
        for item in body.get("results", [])
    ]
    return {
        "kind": "exa",
        "query": query,
        "domains": include_domains,
        "results": results,
        "seconds": round(time.perf_counter() - started, 3),
    }


def file_excerpt_reference(
    root: Path,
    request: dict[str, Any],
    allowed_paths: set[str],
    *,
    maximum_lines: int = 400,
) -> dict[str, Any]:
    relative = str(request.get("path", ""))
    if relative not in allowed_paths:
        raise ValueError(f"file excerpt is outside declared context: {relative}")
    path = safe_path(root, relative)
    if not path.is_file():
        raise ValueError(f"file excerpt target is missing: {relative}")
    start = int(request.get("start_line", 1))
    end = int(request.get("end_line", start + 199))
    if start < 1 or end < start or end - start + 1 > maximum_lines:
        raise ValueError(f"file excerpt must request 1-{maximum_lines} lines")
    lines = path.read_text(errors="replace").splitlines()
    selected = lines[start - 1 : end]
    return {
        "kind": "file_excerpt",
        "query": {"path": relative, "start_line": start, "end_line": end},
        "content": "\n".join(selected),
        "line_count": len(selected),
    }


def render_packet(references: list[dict[str, Any]]) -> str:
    blocks = []
    for reference in references:
        if reference["kind"] == "exa":
            blocks.append("EXA REFERENCE\n" + json.dumps(reference["results"], indent=2))
        else:
            blocks.append(f"LOCAL REFERENCE {reference['query']}\n{reference['content']}")
    return "\n\n".join(blocks)
