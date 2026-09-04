"""Direct local-model completion used by `fresnel ask` and sampling evaluation."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any


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
) -> dict[str, Any]:
    payload = {
        "messages": [
            {"role": "system", "content": system},
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
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    choice = body["choices"][0]
    return {
        "content": choice.get("message", {}).get("content", ""),
        "finish_reason": choice.get("finish_reason"),
        "usage": body.get("usage", {}),
        "seconds": round(time.perf_counter() - started, 3),
    }
