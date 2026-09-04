"""Direct local-model completion used by `fresnel ask` and sampling evaluation."""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from typing import Any


def _payload(
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    min_p: float,
    system: str,
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "messages": [{"role": "system", "content": system}]
        + (messages if messages is not None else [{"role": "user", "content": prompt}]),
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "min_p": min_p,
        "max_tokens": max_tokens,
    }


def _request(endpoint: str, payload: dict[str, Any]) -> urllib.request.Request:
    return urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def complete(
    endpoint: str,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    min_p: float,
    system: str = "You are a concise, accurate local coding assistant.",
    timeout: int = 300,
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload = _payload(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        min_p=min_p,
        system=system,
        messages=messages,
    )
    started = time.perf_counter()
    with urllib.request.urlopen(_request(endpoint, payload), timeout=timeout) as response:
        body = json.load(response)
    choice = body["choices"][0]
    return {
        "content": choice.get("message", {}).get("content", ""),
        "finish_reason": choice.get("finish_reason"),
        "usage": body.get("usage", {}),
        "seconds": round(time.perf_counter() - started, 3),
    }


def stream_complete(
    endpoint: str,
    prompt: str,
    on_text: Callable[[str], None],
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    min_p: float,
    system: str = "You are a concise, accurate local coding assistant.",
    timeout: int = 300,
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Consume an OpenAI-compatible SSE stream and emit text deltas immediately."""
    payload = _payload(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        min_p=min_p,
        system=system,
        messages=messages,
    )
    payload.update({"stream": True, "stream_options": {"include_usage": True}})
    started = time.perf_counter()
    first_token_seconds = None
    content = []
    usage = {}
    finish_reason = None
    with urllib.request.urlopen(_request(endpoint, payload), timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            if not data:
                continue
            event = json.loads(data)
            if event.get("usage"):
                usage = event["usage"]
            choices = event.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            text = choice.get("delta", {}).get("content", "")
            if text:
                if first_token_seconds is None:
                    first_token_seconds = round(time.perf_counter() - started, 3)
                content.append(text)
                on_text(text)
    return {
        "content": "".join(content),
        "finish_reason": finish_reason,
        "usage": usage,
        "seconds": round(time.perf_counter() - started, 3),
        "first_token_seconds": first_token_seconds,
    }
