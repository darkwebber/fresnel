"""Lightweight behavioral sampling tuner for the local coding worker."""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from typing import Any

from .chat import complete

DEFAULT_CANDIDATES = (0.0, 0.15, 0.3, 0.5)


def _exact(text: str) -> bool:
    return text.strip() == "FRESNEL_OK"


def _reasoning(text: str) -> bool:
    try:
        return json.loads(text.strip().removeprefix("```json").removesuffix("```"))["answer"] == 42
    except (json.JSONDecodeError, KeyError, TypeError):
        return False


def _code(text: str) -> bool:
    source = text.strip()
    if source.startswith("```python") and source.endswith("```"):
        source = source[9:-3].strip()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "clamp":
        return False
    arguments = [item.arg for item in functions[0].args.args]
    return arguments == ["value", "low", "high"] and any(
        isinstance(node, ast.Return) for node in ast.walk(functions[0])
    )


TASKS: tuple[tuple[str, str, Callable[[str], bool]], ...] = (
    ("instruction adherence", "Reply with exactly FRESNEL_OK and nothing else.", _exact),
    (
        "compact reasoning",
        'Return only JSON. If 6 workers each finish 7 tasks, return {"answer": total}.',
        _reasoning,
    ),
    (
        "bounded Python",
        "Return only Python code defining clamp(value, low, high). No prose or examples.",
        _code,
    ),
)


def tune(
    endpoint: str,
    *,
    candidates: tuple[float, ...] = DEFAULT_CANDIDATES,
    progress: Callable[[dict], None] | None = None,
    request_fn: Callable[..., dict[str, Any]] = complete,
) -> dict[str, Any]:
    progress = progress or (lambda _event: None)
    results = []
    for temperature in candidates:
        passed = 0
        seconds = 0.0
        tasks = []
        for name, prompt, checker in TASKS:
            label = f"Temperature {temperature:g} · {name}"
            progress({"state": "started", "label": label})
            result = request_fn(
                endpoint,
                prompt,
                max_tokens=256,
                temperature=temperature,
                top_p=0.9,
                top_k=40,
                min_p=0.0,
            )
            success = checker(result["content"])
            passed += int(success)
            seconds += result["seconds"]
            tasks.append({"name": name, "passed": success, **result})
            progress(
                {
                    "state": "completed",
                    "label": label,
                    "seconds": result["seconds"],
                    "memory_free_percent": None,
                    "cached_tokens": result.get("usage", {})
                    .get("prompt_tokens_details", {})
                    .get("cached_tokens", 0),
                }
            )
        results.append(
            {
                "temperature": temperature,
                "score": passed,
                "tasks": tasks,
                "seconds": round(seconds, 3),
            }
        )
    preference = {0.15: 4, 0.3: 3, 0.0: 2, 0.5: 1}
    selected = max(
        results,
        key=lambda item: (
            item["score"],
            preference.get(item["temperature"], 0),
            -item["seconds"],
        ),
    )["temperature"]
    return {"selected_temperature": selected, "results": results}
