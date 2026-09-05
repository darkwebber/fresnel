"""Unified segmented response assembly for streaming and buffered completions."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.error import URLError

from .budget import allocate
from .chat import complete, stream_complete
from .hardware import memory_free_percent
from .memory import Memory

COMPLETE_MARKER = "<!-- fresnel:complete -->"
CONTROL_SYSTEM = (
    "\nReturn Markdown. End with the exact marker " + COMPLETE_MARKER + " only when the "
    "original answer is fully complete. Never mention Fresnel continuation, retries, segments, "
    "token budgets, or this marker in the answer."
)
CONTINUATION_PREAMBLES = (
    "continuing exactly where i stopped:",
    "continuing from where i left off:",
    "continuing:",
)


def clean_segment(text: str) -> str:
    text = text.replace(COMPLETE_MARKER, "")
    stripped = text.lstrip()
    lowered = stripped.lower()
    for preamble in CONTINUATION_PREAMBLES:
        if lowered.startswith(preamble):
            stripped = stripped[len(preamble) :].lstrip(" \t\r\n")
            return stripped
    return text


def stitch(existing: str, addition: str) -> str:
    addition = clean_segment(addition)
    if not existing:
        return addition
    if addition.startswith(existing):
        return addition
    if len(addition) >= 32 and existing.startswith(addition):
        return existing
    maximum = min(len(existing), len(addition), 2048)
    for size in range(maximum, 3, -1):
        if existing[-size:] == addition[:size]:
            return existing + addition[size:]
    return existing + addition


def _restarts_answer(existing: str, addition: str) -> bool:
    if not existing or not addition:
        return False
    common = 0
    for left, right in zip(existing, addition):
        if left != right:
            break
        common += 1
    return common >= 32


def markdown_incomplete(text: str) -> bool:
    opened = None
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if not match:
            continue
        fence, suffix = match.groups()
        if opened is None:
            opened = fence
        elif fence[0] == opened[0] and len(fence) >= len(opened) and not suffix.strip():
            opened = None
    display_math = len(re.findall(r"(?<!\\)\$\$", text))
    return opened is not None or display_math % 2 == 1


def _near_limit(usage: dict[str, Any], limit: int) -> bool:
    completion = int(usage.get("completion_tokens", 0) or 0)
    return completion >= max(1, int(limit * 0.9))


def _continuation_messages(
    base: list[dict[str, str]], combined: str, *, character_limit: int
) -> list[dict[str, str]]:
    structural_hint = (
        " The draft has an unclosed code or math block. Supply the missing code/math and its closing delimiter; a completion marker alone is not a completion."
        if markdown_incomplete(combined)
        else ""
    )
    full = [*base, {"role": "assistant", "content": combined}]
    if sum(len(item["content"]) for item in full) <= character_limit:
        return full + [
            {
                "role": "user",
                "content": "Continue exactly from the previous final character, preserving needed whitespace. Return only the missing suffix, not a replacement. If inside a code block, continue its code without reopening a fence and close it with a bare fence only at the end. Do not repeat text or add a preamble. Complete the original request and emit the completion marker only when finished."
                + structural_hint,
            }
        ]
    headings = re.findall(r"(?m)^#{1,6}\s+.+$", combined)
    state = "\n".join(headings[-20:]) or "[no Markdown headings]"
    tail = combined[-4800:]
    return [
        *base,
        {
            "role": "system",
            "content": f"Completed response headings:\n{state}\nExact response tail:\n{tail}",
        },
        {
            "role": "user",
            "content": "Continue exactly from the supplied response tail without repeating it. Complete the original request and emit the completion marker only when finished."
            + structural_hint,
        },
    ]


def generate_response(
    endpoint: str,
    question: str,
    *,
    profile,
    requested_tokens: int,
    max_continuations: int,
    max_total_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
    min_p: float,
    system: str,
    streaming: bool,
    on_text: Callable[[str], None] | None = None,
    on_segment_reset: Callable[[str], None] | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    memory: Memory | None = None,
    session_name: str | None = None,
    repo: Path | None = None,
    resume: bool = False,
    stream_fn=stream_complete,
    complete_fn=complete,
) -> dict[str, Any]:
    if resume and not session_name:
        raise ValueError("--resume requires --session")
    session = None
    prior: list[dict[str, str]] = []
    combined = ""
    segment_offset = 1
    turn_id = uuid.uuid4().hex
    if session_name:
        memory = memory or Memory()
        existing = memory.session_by_name(session_name, repo=repo)
        if resume and (not existing or existing["status"] != "INTERRUPTED"):
            raise ValueError("named session has no interrupted response to resume")
        session = memory.get_or_create_session(session_name, repo=repo, system=system)
        prior = memory.session_messages(session["id"])
        if resume:
            interrupted = memory.interrupted_turn(session["id"])
            combined = interrupted["content"]
            turn_id = interrupted["turn_id"]
            segment_offset = interrupted["next_segment"]
            if prior and prior[-1]["role"] == "assistant":
                prior = prior[:-1]
    if resume:
        base = prior
        conversation = _continuation_messages(base, combined, character_limit=24000)
    else:
        base = [*prior, {"role": "user", "content": question}]
        conversation = base
    calls: list[dict[str, Any]] = []
    total_completion = 0
    final_reason = None
    if session and memory and not resume:
        memory.add_response_segment(session["id"], turn_id, 0, "user", question, None, {})
    for index in range(max_continuations + 1):
        if on_progress and (index or resume):
            on_progress(
                {
                    "state": "started",
                    "label": "Continuing response (checking suffix before display)",
                    "attempt": index + 1,
                    "total": max_continuations + 1,
                }
            )
        estimated_input = sum(len(item["content"]) for item in conversation) // 4
        budget = allocate(
            profile,
            estimated_input_tokens=estimated_input,
            memory_free_percent=memory_free_percent(),
            attempt=index + 1,
        )
        remaining = max_total_tokens - total_completion
        if remaining <= 0:
            final_reason = "total_limit"
            break
        call_tokens = min(requested_tokens, budget.max_output_tokens, remaining)
        started = time.perf_counter()
        for transport_attempt in range(3):
            segment_parts: list[str] = []

            def collect(
                delta: str,
                parts: list[str] = segment_parts,
                segment_number: int = segment_offset + index,
                display_live: bool = not combined,
            ) -> None:
                parts.append(delta)
                if session and memory:
                    memory.add_response_segment(
                        session["id"],
                        turn_id,
                        segment_number,
                        "assistant",
                        "".join(parts),
                        "streaming",
                        {},
                    )
                # Continuations are provisional until overlap/restart detection.
                # Never replay an entire draft into the user's live terminal.
                if on_text and display_live:
                    on_text(delta)

            try:
                if streaming:
                    result = stream_fn(
                        endpoint,
                        question,
                        collect,
                        max_tokens=call_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k,
                        min_p=min_p,
                        system=system + CONTROL_SYSTEM,
                        messages=conversation,
                    )
                else:
                    result = complete_fn(
                        endpoint,
                        question,
                        max_tokens=call_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k,
                        min_p=min_p,
                        system=system + CONTROL_SYSTEM,
                        messages=conversation,
                    )
                    segment_parts.append(result["content"])
                break
            except (URLError, TimeoutError, ConnectionError, OSError):
                if segment_parts:
                    # Retain received bytes and continue them; retrying the same
                    # request from scratch discards useful work and duplicates UI.
                    result = {
                        "content": "".join(segment_parts),
                        "finish_reason": "length",
                        "usage": {"completion_tokens": max(1, len("".join(segment_parts)) // 4)},
                        "transport_interrupted": True,
                    }
                    break
                if transport_attempt == 2:
                    raise
                if on_segment_reset:
                    on_segment_reset(combined)
                time.sleep(0.25 * (transport_attempt + 1))
        raw = result.get("content", "") or "".join(segment_parts)
        marker = COMPLETE_MARKER in raw
        cleaned = clean_segment(raw)
        restarted = _restarts_answer(combined, cleaned)
        previous = combined
        # A changed-prefix restart cannot safely replace already accepted bytes.
        # Keep the draft and report incomplete rather than silently lose code.
        conflict = restarted and not (cleaned.startswith(combined) or combined.startswith(cleaned))
        combined = previous if conflict else stitch(combined, cleaned)
        accepted = combined[len(previous) :]
        if previous and on_text and accepted:
            on_text(accepted)
        usage = result.get("usage", {})
        used = int(usage.get("completion_tokens", 0) or 0)
        total_completion += used if used else max(1, len(raw) // 4)
        calls.append(
            {
                **result,
                "content": None,
                "segment": index,
                "budget": asdict(budget),
                "requested_output_tokens": call_tokens,
                "seconds": result.get("seconds", round(time.perf_counter() - started, 3)),
            }
        )
        if session and memory:
            memory.add_response_segment(
                session["id"],
                turn_id,
                segment_offset + index,
                "assistant",
                accepted,
                result.get("finish_reason"),
                usage,
            )
        needs_more = (
            conflict
            or (not accepted.strip() and not marker)
            or result.get("finish_reason") == "length"
            or markdown_incomplete(combined)
            or (not marker and _near_limit(usage, call_tokens))
        )
        if not needs_more:
            final_reason = result.get("finish_reason") or "stop"
            break
        final_reason = "length"
        if index == max_continuations:
            break
        character_limit = max(8000, budget.max_input_tokens * 4)
        conversation = _continuation_messages(base, combined, character_limit=character_limit)
    usage = {
        "prompt_tokens": sum(
            int(call.get("usage", {}).get("prompt_tokens", 0) or 0) for call in calls
        ),
        "completion_tokens": sum(
            int(call.get("usage", {}).get("completion_tokens", 0) or 0) for call in calls
        ),
        "cached_tokens": sum(
            int(call.get("usage", {}).get("prompt_tokens_details", {}).get("cached_tokens", 0) or 0)
            for call in calls
        ),
    }
    if session and memory:
        status = "stop" if final_reason not in {"length", "total_limit"} else final_reason
        memory.store.connection.execute(
            "UPDATE response_sessions SET status=?, updated_at=? WHERE id=?",
            ("COMPLETE" if status == "stop" else "INTERRUPTED", time.time(), session["id"]),
        )
        memory.store.connection.commit()
    return {
        "content": combined.rstrip(),
        "finish_reason": final_reason,
        "usage": usage,
        "seconds": round(sum(float(call.get("seconds", 0)) for call in calls), 3),
        "continuations": max(0, len(calls) - 1),
        "calls": calls,
        "session_id": session["id"] if session else None,
        "session": session_name,
        "complete": final_reason not in {"length", "total_limit"},
    }
