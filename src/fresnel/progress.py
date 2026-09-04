"""Small dependency-free terminal progress renderer."""

from __future__ import annotations

import sys
import threading
import time
from typing import Self, TextIO


class BenchmarkProgress:
    """Render a live spinner for blocking benchmark probes on a TTY."""

    frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, stream: TextIO | None = None, *, enabled: bool | None = None):
        self.stream = stream or sys.stderr
        self.enabled = self.stream.isatty() if enabled is None else enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._label = ""
        self._started = 0.0
        self._width = 0

    def __call__(self, event: dict) -> None:
        if not self.enabled:
            return
        state = event["state"]
        if state == "started":
            self._start(str(event["label"]))
        elif state in {"completed", "failed"}:
            self._complete(event, failed=state == "failed")
        elif state == "finished":
            self.stream.write(
                f"\n✓ {event['label']}: {event['selected_profile']} profile "
                f"({event['maximum_context']:,} context / "
                f"{event['maximum_output']:,} output)\n"
            )
            self.stream.flush()

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
