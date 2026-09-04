"""Configuration, paths, profiles, and macOS Keychain helpers."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_NAME = "Fresnel"
MODEL_REPO = "abenzerps/Spark-X2.5-4B-MLX-8bit"
MODEL_REVISION = "92537e99b1c494443ad8e5eea93a2d45f4622a13"
RUNTIME_REPO = "https://github.com/XHToken/Spark-MLX-LLM.git"
RUNTIME_REVISION = "de2b4379fa1e2f2e1f99d84c83f0e008f651d86c"


def application_support() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def cache_dir() -> Path:
    return Path.home() / "Library" / "Caches" / APP_NAME


def logs_dir() -> Path:
    return Path.home() / "Library" / "Logs" / APP_NAME


def config_path() -> Path:
    return application_support() / "config.json"


def state_path() -> Path:
    return application_support() / "fresnel.sqlite3"


@dataclass
class Profile:
    name: str = "balanced"
    context_window: int = 32768
    max_input_tokens: int = 27648
    max_output_tokens: int = 4096
    safety_tokens: int = 1024
    prompt_cache_bytes: int = 2 * 1024**3
    max_attempts: int = 3


@dataclass
class Config:
    protocol_version: str = "1.0"
    model_repo: str = MODEL_REPO
    model_revision: str = MODEL_REVISION
    model_path: str = ""
    runtime_revision: str = RUNTIME_REVISION
    server_executable: str = "spark-mlx-server"
    host: str = "127.0.0.1"
    port: int = 8081
    profile: str = "balanced"
    start_at_login: bool = False
    exa_enabled: bool = False
    active_worker: str = "spark-2.5-4b-mlx-8bit"
    coordinator_input_cost_per_million: float = 0.0
    coordinator_output_cost_per_million: float = 0.0
    profiles: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.profiles is None:
            self.profiles = {"balanced": asdict(Profile())}

    @property
    def selected_profile(self) -> Profile:
        values = dict(self.profiles.get(self.profile, self.profiles["balanced"]))
        return Profile(**values)


def ensure_directories() -> None:
    for path in (application_support(), cache_dir(), logs_dir()):
        path.mkdir(parents=True, exist_ok=True)


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    raw = json.loads(path.read_text())
    known = Config.__dataclass_fields__.keys()
    return Config(**{key: value for key, value in raw.items() if key in known})


def save_config(config: Config, path: Path | None = None) -> Path:
    ensure_directories()
    path = path or config_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(config), indent=2) + "\n")
    temporary.replace(path)
    return path


def keychain_set(account: str, value: str) -> None:
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", "fresnel", "-a", account, "-w", value],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def keychain_get(account: str) -> str | None:
    completed = subprocess.run(
        ["security", "find-generic-password", "-s", "fresnel", "-a", account, "-w"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def environment_key(name: str, account: str) -> str | None:
    return os.environ.get(name) or keychain_get(account)
