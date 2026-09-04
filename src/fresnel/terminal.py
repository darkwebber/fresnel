"""TTY draft display, Markdown/math rendering, and macOS clipboard integration."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import TextIO


@dataclass
class RenderResult:
    content: str
    rendered: bool
    warning: str | None = None


class LiveDraft:
    def __init__(self, stream: TextIO | None = None, *, enabled: bool = True):
        self.stream = stream or sys.stdout
        self.enabled = enabled and self.stream.isatty()
        self.open = False

    def __enter__(self):
        if self.enabled:
            self.stream.write("\x1b[?1049h\x1b[2J\x1b[H")
            self.stream.flush()
            self.open = True
        return self

    def write(self, text: str) -> None:
        if self.enabled:
            self.stream.write(text)
            self.stream.flush()

    def reset(self, content: str) -> None:
        if self.enabled:
            self.stream.write("\x1b[2J\x1b[H" + content)
            self.stream.flush()

    def close(self) -> None:
        if self.open:
            self.stream.write("\x1b[?1049l")
            self.stream.flush()
            self.open = False

    def __exit__(self, _type, _value, _traceback):
        self.close()


def render_markdown(markdown: str, *, mode: str = "auto", width: int | None = None) -> RenderResult:
    if mode == "plain" or not sys.stdout.isatty():
        return RenderResult(markdown, False)
    termtex = shutil.which("termtex")
    glow = shutil.which("glow")
    missing = [name for name, path in (("termtex", termtex), ("glow", glow)) if not path]
    if missing:
        return RenderResult(markdown, False, f"renderer unavailable: {', '.join(missing)}")
    columns = width or shutil.get_terminal_size((100, 24)).columns
    columns = max(40, min(columns, 120))
    ascii_mode = os.environ.get("TERM") == "dumb"
    termtex_command = [termtex, "-md"] + (["-ascii"] if ascii_mode else [])
    try:
        math = subprocess.run(
            termtex_command,
            input=markdown,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        rendered = subprocess.run(
            [glow, "-w", str(columns), "-"],
            input=math.stdout,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
            env={**os.environ, "GLAMOUR_STYLE": "notty" if os.environ.get("NO_COLOR") else "auto"},
        )
        return RenderResult(rendered.stdout.rstrip(), True)
    except (OSError, subprocess.SubprocessError) as exc:
        return RenderResult(markdown, False, f"renderer failed: {type(exc).__name__}")


def copy_markdown(markdown: str) -> tuple[bool, str | None]:
    pbcopy = "/usr/bin/pbcopy"
    if not os.path.isfile(pbcopy):
        return False, "pbcopy is unavailable"
    try:
        subprocess.run(
            [pbcopy], input=markdown, text=True, check=True, timeout=5, stdout=subprocess.DEVNULL
        )
        return True, None
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"clipboard failed: {type(exc).__name__}"
