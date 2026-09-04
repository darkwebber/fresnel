"""Spark worker protocol, prompt rendering, and constrained file operations."""

from __future__ import annotations

import ast
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

from .protocol import Component, safe_path

EDIT_RE = re.compile(
    r'<<<EDIT path="(?P<path>[^"\n]+)">>>\s*<<<SEARCH>>>[ \t]*\n?(?P<search>.*?)\n?'
    r"<<<REPLACE>>>[ \t]*\n?(?P<replace>.*?)\n?<<<END>>>",
    re.DOTALL,
)
CREATE_RE = re.compile(
    r'<<<CREATE path="(?P<path>[^"\n]+)">>>\n(?P<content>.*?)\n<<<END>>>', re.DOTALL
)
REFERENCE_RE = re.compile(r"<<<NEEDS_REFERENCE>>>\s*(\{.*?\})\s*<<<END>>>", re.DOTALL)
ACTION_RE = re.compile(r"<<<REQUEST_ACTION>>>\s*(\{.*?\})\s*<<<END>>>", re.DOTALL)
LOOSE_REPLACE_RE = re.compile(
    r"<{2,3}REQUEST_ACTION>{2,3}\s*(?:<<<)?SEARCH(?:>>>)?\s*\n(?P<search>.*?)\n"
    r"(?:<<<)?REPLACE(?:>>>)?\s*\n(?P<replace>.*?)\n(?:<<<)?END(?:>>>)?(?:\s*<<<)?",
    re.DOTALL,
)


def render_prompt(
    component: Component, root: Path, references: str = "", feedback: str = ""
) -> str:
    blocks = []
    for relative in dict.fromkeys(component.targets + component.context):
        path = safe_path(root, relative)
        if path.is_file():
            content = path.read_text(errors="replace")
        elif relative in component.targets:
            content = "[FILE DOES NOT EXIST — use CREATE]"
        else:
            raise ValueError(f"missing context file: {relative}")
        blocks.append(f'FILE "{relative}"\n<<<CONTENT>>>\n{content}\n<<<END_CONTENT>>>')
    return f"""You are Spark 2.5, a bounded coding worker. Execute the supplied design; do not redesign it.

TASK:\n{component.task}
TARGETS:\n{chr(10).join("- " + value for value in component.targets)}
CONSTRAINTS:\n{chr(10).join("- " + value for value in component.constraints)}
ACCEPTANCE:\n{chr(10).join("- " + value for value in component.acceptance)}
REQUIRED IMPLEMENTATION:\n{chr(10).join("- " + value for value in component.implementation)}
VERIFIED REFERENCES:\n{references or "[none]"}
VALIDATION FEEDBACK:\n{feedback or "[first attempt]"}
FILES:\n{chr(10).join(blocks)}

Return only exact operations. Existing files use SEARCH/REPLACE:
<<<EDIT path="relative.py">>><<<SEARCH>>>
unique exact text
<<<REPLACE>>>
replacement
<<<END>>>

Missing target files use:
<<<CREATE path="relative.py">>>
complete content
<<<END>>>

If an API fact is missing, return one JSON request between NEEDS_REFERENCE and END markers.
For any other required action, return one JSON request between REQUEST_ACTION and END markers.
Do not include prose or Markdown fences."""


def call(
    endpoint: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout: int = 300,
    *,
    temperature: float = 0.15,
    top_p: float = 0.9,
    top_k: int = 40,
    min_p: float = 0.0,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Follow the bounded edit protocol exactly. Never explain.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "min_p": min_p,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    choice = body["choices"][0]
    usage = dict(body.get("usage", {}))
    usage["finish_reason"] = choice.get("finish_reason")
    if choice.get("finish_reason") == "length":
        raise ValueError("finish_reason length: worker output was truncated")
    return choice["message"].get("content", ""), usage


def parse(text: str, fallback_target: str | None = None) -> tuple[str, Any]:
    stripped = text.strip()
    for kind, pattern in (("reference", REFERENCE_RE), ("action", ACTION_RE)):
        match = pattern.fullmatch(stripped)
        if match:
            return kind, json.loads(match.group(1))
    operations = [{"kind": "edit", **match.groupdict()} for match in EDIT_RE.finditer(text)]
    operations.extend({"kind": "create", **match.groupdict()} for match in CREATE_RE.finditer(text))
    residue = CREATE_RE.sub("", EDIT_RE.sub("", text)).strip()
    if operations and not residue:
        return "operations", operations
    if fallback_target:
        loose = LOOSE_REPLACE_RE.fullmatch(stripped)
        if loose:
            return "operations", [
                {
                    "kind": "edit",
                    "path": fallback_target,
                    "search": loose.group("search"),
                    "replace": loose.group("replace"),
                }
            ]
        try:
            request = json.loads(stripped)
        except json.JSONDecodeError:
            request = None
        action = None
        if isinstance(request, dict):
            action = (
                request.get("REQUEST_ACTION")
                or request.get("action")
                or request.get("request_action")
            )
            if (
                request.get("request") == "REQUEST_ACTION"
                and "search" in request
                and "replace" in request
            ):
                action = "REPLACE"
        search = request.get("SEARCH", request.get("search")) if isinstance(request, dict) else None
        replacement = (
            request.get("REPLACE", request.get("replace")) if isinstance(request, dict) else None
        )
        supplied_path = (
            request.get("file") or request.get("path") if isinstance(request, dict) else None
        )
        if (
            isinstance(request, dict)
            and str(action).upper() == "REPLACE"
            and supplied_path == fallback_target
            and isinstance(search, str)
            and isinstance(replacement, str)
        ):
            return "operations", [
                {
                    "kind": "edit",
                    "path": fallback_target,
                    "search": search,
                    "replace": replacement,
                }
            ]
    # Some small models reliably emit a complete file but miss the envelope.
    # Accept that only for one predeclared Python target and only when the whole
    # response is syntactically valid Python (possibly in one Markdown fence).
    if fallback_target and fallback_target.endswith(".py"):
        candidate = stripped
        fence = re.fullmatch(r"```(?:python)?\s*\n(.*?)\n```", candidate, re.DOTALL)
        if fence:
            candidate = fence.group(1)
        try:
            module = ast.parse(candidate)
        except SyntaxError:
            pass
        else:
            meaningful = (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Import,
                ast.ImportFrom,
                ast.Assign,
                ast.AnnAssign,
            )
            if any(isinstance(node, meaningful) for node in module.body):
                return "operations", [
                    {"kind": "create", "path": fallback_target, "content": candidate}
                ]
    raise ValueError("worker returned an invalid operation response")


def apply_operations(
    root: Path,
    targets: set[str],
    operations: list[dict[str, str]],
    *,
    replace_existing_create: bool = False,
    replacement_size_limit: int = 64 * 1024,
) -> list[str]:
    changed = set()
    for operation in operations:
        relative = operation["path"]
        if relative not in targets:
            raise ValueError(f"worker attempted a non-target file: {relative}")
        path = safe_path(root, relative)
        if operation["kind"] == "create":
            if path.exists():
                if not replace_existing_create or path.stat().st_size > replacement_size_limit:
                    raise ValueError(f"CREATE target exists: {relative}")
                path.write_text(operation["content"])
                changed.add(relative)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(operation["content"])
        else:
            if not path.is_file():
                raise ValueError(f"EDIT target is missing: {relative}")
            content = path.read_text()
            search = operation["search"]
            if content.count(search) != 1:
                raise ValueError(f"SEARCH must match exactly once in {relative}")
            path.write_text(content.replace(search, operation["replace"], 1))
        changed.add(relative)
    return sorted(changed)
