"""Fast dashboard view model and graceful terminal rendering."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any

from .config import load_config
from .memory import Memory
from .setup import doctor
from .store import Store


def view_model() -> dict[str, Any]:
    store = Store()
    memory = Memory(store)
    try:
        health = doctor()
        config = load_config()
        return {
            "title": "FRESNEL",
            "subtitle": "Your local implementation control plane",
            "healthy": health["healthy"],
            "worker": "ready" if health["worker_endpoint"]["reachable"] else "idle",
            "chip": health["hardware"]["chip"],
            "memory_free_percent": health["memory_free_percent"],
            "profile": config.profile,
            "personalization": memory.personalization_enabled(),
            "runs": store.recent_runs(5),
            "actions": [
                "fresnel run --repo . --plan plan.json",
                "fresnel status --follow --run RUN_ID",
                "fresnel ask \"your question\"",
                "fresnel doctor --fix",
            ],
        }
    finally:
        memory.close()


def render(model: dict[str, Any]) -> None:
    native = shutil.which("fresnel-ui")
    if native and sys.stdout.isatty():
        completed = subprocess.run(
            [native, "dashboard"],
            input=json.dumps(model),
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    cyan = "\033[36m" if color else ""
    green = "\033[32m" if color else ""
    reset = "\033[0m" if color else ""
    print(f"{cyan}╭─ FRESNEL ─────────────────────────────────────────╮{reset}")
    print(f"{cyan}│{reset}  Your local implementation control plane              {cyan}│{reset}")
    print(f"{cyan}╰────────────────────────────────────────────────────╯{reset}")
    state = "healthy" if model["healthy"] else "needs attention"
    print(f"\n  {green if model['healthy'] else ''}●{reset} {state} · worker {model['worker']}")
    print(
        f"  {model['chip']} · {model['memory_free_percent']}% memory free · "
        f"{model['profile']} profile"
    )
    if model["runs"]:
        print("\n  Recent tasks")
        for run in model["runs"]:
            print(f"    {run['id'][:8]}  {run['status']:<18} {run['request'][:45]}")
    print("\n  Try: fresnel ask \"Explain this project\"\n")
