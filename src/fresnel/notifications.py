"""Narrow macOS notification boundary for consequential run events."""

from __future__ import annotations

import platform
import subprocess


def notify(title: str, message: str) -> bool:
    if platform.system() != "Darwin":
        return False
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')[:120]
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')[:240]
    completed = subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            f'display notification "{safe_message}" with title "{safe_title}"',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
    )
    return completed.returncode == 0
