"""Small dependency-free terminal progress renderer."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Self, TextIO


class BenchmarkProgress:
    """Render terminal haptics or structured progress events for an orchestrator."""

    frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        enabled: bool | None = None,
        mode: str | None = None,
    ):
        self.stream = stream or sys.stderr
        selected = mode or os.environ.get("FRESNEL_PROGRESS", "auto")
        if selected not in {"auto", "json", "none"}:
            raise ValueError("progress mode must be auto, json, or none")
        self.json = selected == "json"
        self.linear = bool(
            os.environ.get("FRESNEL_SCREEN_READER")
            or os.environ.get("FRESNEL_REDUCE_MOTION")
            or os.environ.get("CI")
        )
        self.enabled = (
            selected != "none"
            and (self.json or (self.stream.isatty() if enabled is None else enabled))
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._label = ""
        self._started = 0.0
        self._width = 0
        self._last_linear_label = ""

    def __call__(self, event: dict) -> None:
        if not self.enabled:
            return
        event = {"timestamp": round(time.time(), 3), **event}
        if self.json:
            self.stream.write("FRESNEL_PROGRESS " + json.dumps(event, separators=(",", ":")) + "\n")
            self.stream.flush()
            return
        state = event["state"]
        if self.linear:
            label = self._display_label(event)
            if label != self._last_linear_label or state in {"completed", "failed", "finished"}:
                marker = "✓" if state in {"completed", "finished"} else "✗" if state == "failed" else "•"
                self.stream.write(f"{marker} {label}\n")
                self.stream.flush()
                self._last_linear_label = label
            return
        if state == "started":
            self._start(self._display_label(event))
        elif state == "updated":
            self._label = self._display_label(event)
        elif state in {"completed", "failed"}:
            self._complete(event, failed=state == "failed")
        elif state == "finished":
            self.stream.write(
                f"\n✓ {event['label']}: {event['selected_profile']} profile "
                f"({event['maximum_context']:,} context / "
                f"{event['maximum_output']:,} output)\n"
            )
            self.stream.flush()

    @staticmethod
    def _display_label(event: dict) -> str:
        label = str(event["label"])
        current = event.get("progress")
        total = event.get("total")
        if isinstance(current, (int, float)) and isinstance(total, (int, float)) and total:
            if event.get("phase") == "download":
                label += f" · {current / 1024**2:.1f}/{total / 1024**2:.1f} MB"
            else:
                label += f" · {current:g}/{total:g}"
        free = event.get("memory_free_percent")
        if free is not None:
            label += f" · memory {free}%"
        eta = event.get("eta_seconds", "absent")
        if eta is None:
            return label + " · ETA estimating"
        if eta != "absent":
            return label + f" · ETA {eta}s"
        return label

    def _start(self, label: str) -> None:
        self.close()
        self._label = label
        self._started = time.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def _animate(self) -> None:
        frame = 0
        while not self._stop.wait(0.1):
            elapsed = int(time.monotonic() - self._started)
            text = f"{self.frames[frame % len(self.frames)]} {self._label} · {elapsed}s"
            self._width = max(self._width, len(text))
            self.stream.write("\r" + text.ljust(self._width))
            self.stream.flush()
            frame += 1

    def _complete(self, event: dict, *, failed: bool) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        seconds = event.get("seconds", round(time.monotonic() - self._started, 1))
        if failed:
            text = f"✗ {event['label']} · failed after {seconds}s · {event.get('error', '')}"
        else:
            free = event.get("memory_free_percent")
            memory = f" · memory free {free}%" if free is not None else ""
            cache = event.get("cached_tokens", 0)
            cached = f" · cached {cache:,}" if cache else ""
            text = f"✓ {event['label']} · {seconds}s{memory}{cached}"
        self.stream.write("\r" + text.ljust(self._width) + "\n")
        self.stream.flush()
        self._thread = None
        self._width = 0

    def close(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=1)
            self.stream.write("\n")
            self.stream.flush()
        self._thread = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args) -> None:
        self.close()
