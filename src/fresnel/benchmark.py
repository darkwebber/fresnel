"""Adaptive endpoint calibration and profile selection."""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from .config import Profile
from .hardware import detect, memory_free_percent, swap_used, thermal_state

CONTEXT_CANDIDATES = (4096, 8192, 16384, 24576, 32768)
OUTPUT_CANDIDATES = (512, 1024, 2048, 4096, 8192)
Progress = Callable[[dict[str, Any]], None]


def tokenish_prompt(tokens: int) -> str:
    unit = "The function is deterministic, bounded, tested, and preserves its input. "
    return (unit * max(1, tokens // 14))[: tokens * 4]


def request(endpoint: str, prompt: str, max_tokens: int, timeout: int = 300) -> dict[str, Any]:
    payload = {
        "messages": [{"role": "user", "content": prompt + "\nReply with exactly OK."}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    started = time.perf_counter()
    before_swap = swap_used()
    call = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(call, timeout=timeout) as response:
        body = json.load(response)
    elapsed = time.perf_counter() - started
    usage = body.get("usage", {})
    timings = body.get("timings", {})
    return {
        "requested_output_tokens": max_tokens,
        "seconds": round(elapsed, 3),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "cached_tokens": usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "peak_memory_gb": timings.get("peak_memory"),
        "swap_delta_bytes": max(0, swap_used() - before_swap),
        "thermal_state": thermal_state(),
        "memory_free_percent": memory_free_percent(),
        "ok": body.get("choices", [{}])[0].get("message", {}).get("content", "").strip() == "OK",
    }


def safe(result: dict[str, Any]) -> bool:
    return (
        result["ok"]
        and result["swap_delta_bytes"] <= 256 * 1024**2
        and result["thermal_state"] not in {"serious", "critical"}
        and (result.get("memory_free_percent") is None or result["memory_free_percent"] >= 20)
    )


def select_profiles(maximum_context: int, maximum_output: int) -> dict[str, dict[str, Any]]:
    def build(name: str, context: int, output: int, cache_gb: int) -> dict[str, Any]:
        reserve = 1024
        return asdict(
            Profile(
                name=name,
                context_window=context,
                max_input_tokens=max(1024, context - output - reserve),
                max_output_tokens=output,
                safety_tokens=reserve,
                prompt_cache_bytes=cache_gb * 1024**3,
            )
        )

    return {
        "eco": build("eco", min(16384, maximum_context), min(2048, maximum_output), 1),
        "balanced": build("balanced", min(24576, maximum_context), min(4096, maximum_output), 2),
        "maximum": build("maximum", maximum_context, maximum_output, 2),
    }


def calibrate(
    endpoint: str, *, quick: bool = False, progress: Progress | None = None
) -> dict[str, Any]:
    hardware = detect()
    contexts = (4096, 8192) if quick else CONTEXT_CANDIDATES
    outputs = (512, 2048) if quick else OUTPUT_CANDIDATES
    progress = progress or (lambda _event: None)

    def probe(label: str, prompt: str, output: int, **metadata: Any) -> dict[str, Any]:
        progress({"state": "started", "label": label, **metadata})
        started = time.perf_counter()
        try:
            result = request(endpoint, prompt, output)
        except Exception as exc:
            progress(
                {
                    "state": "failed",
                    "label": label,
                    "seconds": round(time.perf_counter() - started, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                    **metadata,
                }
            )
            raise
        progress({"state": "completed", "label": label, **metadata, **result})
        return result

    # Model loading is lazy in MLX LM. Exclude that one-time allocation and
    # compilation cost from context-pressure decisions.
    warmup = probe("Loading model and warming up", "Warm up the model.", 8, probe="warmup")
    warmup["probe"] = "warmup"
    results = [warmup]
    maximum_context = 4096
    last_prompt = tokenish_prompt(4096 - 128)
    for context in contexts:
        last_prompt = tokenish_prompt(context - 128)
        result = probe(
            f"Testing {context:,}-token context",
            last_prompt,
            8,
            probe="context",
            target_context=context,
        )
        result["probe"] = "context"
        result["target_context"] = context
        results.append(result)
        if not safe(result):
            break
        maximum_context = context
    cache_probe = probe(
        "Checking repeated-prompt cache", last_prompt, 8, probe="repeated_prompt_cache"
    )
    cache_probe["probe"] = "repeated_prompt_cache"
    prior = results[-1]
    cache_probe["latency_speedup"] = (
        round(prior["seconds"] / cache_probe["seconds"], 3) if cache_probe["seconds"] else None
    )
    results.append(cache_probe)
    maximum_output = 512
    for output in outputs:
        if output + 1024 >= maximum_context:
            break
        result = probe(
            f"Testing {output:,}-token output reserve",
            "Health check only.",
            output,
            probe="output_ceiling",
            target_output_limit=output,
        )
        result["probe"] = "output_ceiling"
        result["target_output_limit"] = output
        results.append(result)
        if not safe(result):
            break
        maximum_output = output
    profiles = select_profiles(maximum_context, maximum_output)
    selected = "eco" if hardware.power_source == "battery" else "balanced"
    progress(
        {
            "state": "finished",
            "label": "Calibration complete",
            "selected_profile": selected,
            "maximum_context": maximum_context,
            "maximum_output": maximum_output,
        }
    )
    return {
        "hardware": hardware.json(),
        "results": results,
        "profiles": profiles,
        "selected_profile": selected,
        "note": "Sampling temperature is fixed at 0; thermal_state describes physical pressure.",
    }
