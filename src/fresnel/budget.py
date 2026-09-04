"""Context/output allocation that reacts to prompt size, retries, and Mac pressure."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Profile


@dataclass(frozen=True)
class CallBudget:
    max_input_tokens: int
    max_output_tokens: int
    memory_free_percent: int | None
    pressure: str


def allocate(
    profile: Profile,
    *,
    estimated_input_tokens: int = 0,
    memory_free_percent: int | None = None,
    attempt: int = 1,
) -> CallBudget:
    """Reserve output first and compact input more aggressively on retries/pressure."""
    free = memory_free_percent
    if free is not None and free < 12:
        pressure, factor, output_cap = "critical", 0.35, 1024
    elif free is not None and free < 20:
        pressure, factor, output_cap = "high", 0.5, 2048
    elif free is not None and free < 30:
        pressure, factor, output_cap = "moderate", 0.75, 4096
    else:
        pressure, factor, output_cap = "normal", 1.0, 8192

    retry_factor = max(0.55, 1.0 - 0.15 * (attempt - 1))
    input_limit = max(2048, int(profile.max_input_tokens * factor * retry_factor))
    used_input = min(max(0, estimated_input_tokens), input_limit)
    available_output = max(
        256, profile.context_window - used_input - profile.safety_tokens
    )
    output_limit = min(output_cap, 8192, available_output)
    if output_limit < min(1024, profile.max_output_tokens):
        input_limit = max(
            2048,
            profile.context_window - min(1024, profile.max_output_tokens) - profile.safety_tokens,
        )
        available_output = profile.context_window - min(used_input, input_limit) - profile.safety_tokens
        output_limit = min(output_cap, 8192, max(256, available_output))
    return CallBudget(input_limit, output_limit, free, pressure)
