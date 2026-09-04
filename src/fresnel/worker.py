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


class WorkerTruncated(ValueError):
    def __init__(self, content: str, usage: dict[str, Any]):
        super().__init__("finish_reason length: worker output was truncated")
        self.content = content
        self.usage = usage


def _bounded_content(content: str, character_limit: int, relative: str) -> str:
    if len(content) <= character_limit:
        return content
    marker = (
        f"\n[... {len(content) - character_limit:,} characters omitted from {relative}; "
        "request a file_excerpt for the needed line range ...]\n"
    )
    usable = max(200, character_limit - len(marker))
    head = int(usable * 0.6)
    return content[:head] + marker + content[-(usable - head) :]


def render_prompt(
    component: Component,
    root: Path,
    references: str = "",
    feedback: str = "",
    *,
    goal: str | None = None,
    max_input_tokens: int | None = None,
    response_budget: int | None = None,
    attempt: int = 1,
) -> str:
    input_characters = max_input_tokens * 4 if max_input_tokens else 10**9
    reference_limit = min(12000, max(2000, input_characters // 5))
    references = _bounded_content(references, reference_limit, "reference packet")
    paths = tuple(dict.fromkeys(component.targets + component.context))
    fixed_estimate = 5000 + len(feedback) + len(references) + len(goal or "")
    available_file_characters = max(1000, input_characters - fixed_estimate)
    per_file_limit = max(300, available_file_characters // max(1, len(paths)))
    blocks = []
    for relative in paths:
        path = safe_path(root, relative)
        if path.is_file():
            raw_content = path.read_text(errors="replace")
            line_count = len(raw_content.splitlines())
            content = _bounded_content(raw_content, per_file_limit, relative)
            description = f"{line_count} lines"
        elif relative in component.targets:
            content = "[FILE DOES NOT EXIST — use CREATE]"
            description = "missing target"
        else:
            raise ValueError(f"missing context file: {relative}")
        blocks.append(
            f'FILE "{relative}" ({description})\n<<<CONTENT>>>\n{content}\n<<<END_CONTENT>>>'
        )
    return f"""You are Spark 2.5, a bounded coding worker. Execute the supplied design; do not redesign it.

ATTEMPT: {attempt}
OUTPUT BUDGET: {response_budget or '[profile default]'} tokens. Use the smallest complete edit.

OVERALL GOAL:\n{goal or component.task}
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
If file content was omitted, request only the needed range:
<<<NEEDS_REFERENCE>>>{{"kind":"file_excerpt","path":"relative.py","start_line":1,"end_line":200}}<<<END>>>
For any other required action, return one JSON request between REQUEST_ACTION and END markers.
Do not include prose or Markdown fences. Never sacrifice a closing END marker. Prefer a small
SEARCH/REPLACE over recreating a whole existing file."""


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
        raise WorkerTruncated(choice["message"].get("content", ""), usage)
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
