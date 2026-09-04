"""Guided macOS setup, model discovery, runtime installation, and service management."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .benchmark import calibrate
from .config import (
    MODEL_REPO,
    MODEL_REVISION,
    RUNTIME_REPO,
    RUNTIME_REVISION,
    Config,
    application_support,
    ensure_directories,
    load_config,
    logs_dir,
    save_config,
)
from .hardware import detect, memory_free_percent, validate_supported


def model_snapshot() -> Path | None:
    root = Path.home() / ".cache" / "huggingface" / "hub"
    candidate = root / f"models--{MODEL_REPO.replace('/', '--')}" / "snapshots" / MODEL_REVISION
    required = ("config.json", "tokenizer.json")
    has_weights = any(candidate.glob("*.safetensors"))
    return (
        candidate
        if candidate.is_dir()
        and has_weights
        and all((candidate / name).exists() for name in required)
        else None
    )


def server_healthy(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/v1/models", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_server(config: Config, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_healthy(config.host, config.port):
            return
        time.sleep(0.5)
    raise RuntimeError(f"worker did not become healthy on {config.host}:{config.port}")


def available_port(preferred: int = 8081) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket() as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free loopback port found between 8081 and 8100")


def install_runtime(*, dry_run: bool = False) -> list[str]:
    requirement = f"git+{RUNTIME_REPO}@{RUNTIME_REVISION}"
    uv = shutil.which("uv")
    command = (
        [uv, "pip", "install", "--python", sys.executable, requirement, "huggingface-hub>=0.34,<2"]
        if uv
        else [sys.executable, "-m", "pip", "install", requirement, "huggingface-hub>=0.34,<2"]
    )
    if not dry_run:
        subprocess.run(command, check=True)
    return command


def download_model(*, dry_run: bool = False) -> Path:
    expected = model_snapshot()
    if expected:
        return expected
    if dry_run:
        return Path.home() / ".cache" / "huggingface" / "hub" / "dry-run-spark-model"
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface-hub is not installed; run Fresnel runtime setup first"
        ) from exc
    return Path(snapshot_download(repo_id=MODEL_REPO, revision=MODEL_REVISION))


def server_command(config: Config) -> list[str]:
    profile = config.selected_profile
    model = config.model_path or str(model_snapshot() or "")
    if not model:
        raise RuntimeError("pinned Spark model is not downloaded; run `fresnel setup`")
    return [
        config.server_executable,
        "--model",
        model,
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--max-tokens",
        str(profile.max_output_tokens),
        "--chat-template-args",
        '{"enable_thinking":false}',
        "--prefill-step-size",
        "2048",
        "--prompt-cache-size",
        "1",
        "--prompt-cache-bytes",
        str(profile.prompt_cache_bytes),
        "--decode-concurrency",
        "1",
        "--prompt-concurrency",
        "1",
        "--log-level",
        "INFO",
    ]


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "ai.fresnel.worker.plist"


def render_launch_agent(config: Config) -> str:
    arguments = "\n".join(f"      <string>{value}</string>" for value in server_command(config))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.fresnel.worker</string>
  <key>ProgramArguments</key><array>
{arguments}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{logs_dir() / "worker.log"}</string>
  <key>StandardErrorPath</key><string>{logs_dir() / "worker-error.log"}</string>
</dict></plist>
"""


def install_service(config: Config, *, dry_run: bool = False) -> Path:
    path = launch_agent_path()
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_launch_agent(config))
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], check=False)
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)
    return path


def doctor() -> dict:
    hardware = detect()
    config = load_config()
    problems = validate_supported(hardware)
    snapshot = model_snapshot()
    if not shutil.which(config.server_executable):
        problems.append(f"server executable is unavailable: {config.server_executable}")
    if not snapshot and not (config.model_path and Path(config.model_path).is_dir()):
        problems.append("pinned Spark model is not downloaded")
    free_percent = memory_free_percent()
    warnings = []
    if free_percent is not None and free_percent < 20:
        warnings.append("less than 20% system memory is currently free; use the eco profile")
    if hardware.thermal_state in {"serious", "critical"}:
        warnings.append("macOS reports thermal pressure; postpone calibration")
    return {
        "healthy": not problems,
        "hardware": hardware.json(),
        "config": config.__dict__,
        "model_snapshot": str(snapshot) if snapshot else None,
        "problems": problems,
        "warnings": warnings,
        "memory_free_percent": free_percent,
    }


def guided_setup(
    *,
    assume_yes: bool = False,
    dry_run: bool = False,
    skip_benchmark: bool = False,
    quick_benchmark: bool = False,
    with_service: bool = False,
    confirm: Callable[[str], bool] | None = None,
) -> dict:
    confirm = confirm or (
        lambda question: (
            assume_yes or input(f"{question} [Y/n] ").strip().lower() in {"", "y", "yes"}
        )
    )
    ensure_directories()
    hardware = detect()
    problems = validate_supported(hardware)
    if problems:
        raise RuntimeError("; ".join(problems))
    actions = []
    if not shutil.which("spark-mlx-server"):
        if not confirm("Install the pinned Spark MLX runtime and Hugging Face downloader?"):
            raise RuntimeError("Spark runtime installation was declined")
        actions.append({"runtime_command": install_runtime(dry_run=dry_run)})
    model = model_snapshot()
    if not model:
        if not confirm(f"Download {MODEL_REPO} 8-bit (approximately 4.1 GB)?"):
            raise RuntimeError("model download was declined")
        model = download_model(dry_run=dry_run)
        actions.append({"downloaded_model": str(model)})
    config = load_config()
    config.model_path = str(model)
    if not server_healthy(config.host, config.port):
        config.port = available_port(config.port)
    benchmark_result = None
    worker = None
    if not skip_benchmark and not dry_run and not server_healthy(config.host, config.port):
        log_path = logs_dir() / "setup-worker.log"
        log = log_path.open("a")
        worker = subprocess.Popen(server_command(config), stdout=log, stderr=subprocess.STDOUT)
        actions.append({"temporary_worker_pid": worker.pid, "log": str(log_path)})
        try:
            wait_for_server(config)
        except Exception:
            worker.terminate()
            worker.wait(timeout=15)
            log.close()
            raise
    if not skip_benchmark and not dry_run:
        try:
            benchmark_result = calibrate(
                f"http://{config.host}:{config.port}/v1/chat/completions",
                quick=quick_benchmark,
            )
            config.profiles = benchmark_result["profiles"]
            config.profile = benchmark_result["selected_profile"]
        finally:
            if worker is not None:
                worker.terminate()
                worker.wait(timeout=15)
                log.close()
    if with_service:
        config.start_at_login = True
        service = install_service(config, dry_run=dry_run)
        actions.append({"service": str(service)})
    if not dry_run:
        save_config(config)
    return {
        "hardware": hardware.json(),
        "config": config.__dict__,
        "actions": actions,
        "benchmark": benchmark_result,
        "next": "Run `fresnel serve`, then install an adapter with `fresnel integrations install codex`.",
    }


def uninstall_setup(*, purge_state: bool = False, dry_run: bool = False) -> dict:
    """Remove Fresnel-owned service/config state while preserving model caches."""
    service = launch_agent_path()
    removed = []
    if service.exists():
        removed.append(str(service))
        if not dry_run:
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}", str(service)], check=False
            )
            service.unlink()
    if purge_state and application_support().exists():
        removed.append(str(application_support()))
        if not dry_run:
            shutil.rmtree(application_support())
    return {
        "removed": removed,
        "preserved": ["Hugging Face model cache", str(Path.home() / ".cache" / "huggingface")],
        "dry_run": dry_run,
    }
