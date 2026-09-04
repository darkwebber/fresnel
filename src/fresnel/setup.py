"""Guided macOS setup, model discovery, runtime installation, and service management."""

from __future__ import annotations

import json
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
    runtime_dir,
    save_config,
)
from .hardware import detect, memory_free_percent, validate_supported


def runtime_executable(name: str) -> str | None:
    """Find a runtime command in Fresnel's private environment or the user PATH."""
    stable = runtime_dir() / "bin" / name
    if stable.is_file() and os.access(stable, os.X_OK):
        return str(stable)
    private = Path(sys.executable).parent / name
    if private.is_file() and os.access(private, os.X_OK):
        return str(private)
    return shutil.which(name)


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


def server_models(host: str, port: int, *, timeout: float = 0.5) -> list[str]:
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/v1/models", timeout=timeout
        ) as response:
            body = json.load(response)
        return [str(item["id"]) for item in body.get("data", []) if item.get("id")]
    except Exception:
        return []


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


def install_runtime(*, dry_run: bool = False) -> list[list[str]]:
    requirement = f"git+{RUNTIME_REPO}@{RUNTIME_REVISION}"
    uv = shutil.which("uv")
    environment = runtime_dir()
    runtime_python = environment / "bin" / "python"
    if uv:
        create = [uv, "venv", "--python", sys.executable, str(environment)]
        command = [
            uv,
            "pip",
            "install",
            "--python",
            str(runtime_python),
            requirement,
            "huggingface-hub>=0.34,<2",
        ]
    else:
        create = [sys.executable, "-m", "venv", str(environment)]
        command = [
            str(runtime_python),
            "-m",
            "pip",
            "install",
            requirement,
            "huggingface-hub>=0.34,<2",
        ]
    if not dry_run:
        ensure_directories()
        subprocess.run(create, check=True)
        subprocess.run(command, check=True)
        if not runtime_executable("spark-mlx-server"):
            raise RuntimeError(
                "Spark runtime installed but its server entry point was not created in "
                f"{environment / 'bin'}"
            )
    return [create, command]


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
    executable = (
        config.server_executable
        if Path(config.server_executable).is_absolute()
        and Path(config.server_executable).is_file()
        else runtime_executable(Path(config.server_executable).name)
    )
    if not executable:
        raise RuntimeError(
            "Spark server is unavailable; run `fresnel doctor --fix --yes` to install it"
        )
    return [
        executable,
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
    if not runtime_executable(Path(config.server_executable).name):
        problems.append(f"server executable is unavailable: {config.server_executable}")
    if not snapshot and not (config.model_path and Path(config.model_path).is_dir()):
        problems.append("pinned Spark model is not downloaded")
    free_percent = memory_free_percent()
    warnings = []
    advertised_models = server_models(config.host, config.port)
    requested_model = config.model_path or config.model_repo
    selected_model = (
        requested_model
        if requested_model in advertised_models
        else advertised_models[0]
        if advertised_models
        else None
    )
    if advertised_models and requested_model not in advertised_models:
        warnings.append(
            "configured model ID is not advertised by the running server; "
            "worker calls will retry with the server default"
        )
    output_tools = {
        "glow": shutil.which("glow"),
        "termtex": shutil.which("termtex"),
        "pbcopy": shutil.which("pbcopy") or ("/usr/bin/pbcopy" if Path("/usr/bin/pbcopy").is_file() else None),
    }
    missing_output_tools = [name for name, path in output_tools.items() if not path]
    if missing_output_tools:
        warnings.append(
            "optional terminal output helpers are unavailable: "
            + ", ".join(missing_output_tools)
            + "; answers will fall back gracefully"
        )
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
        "output_tools": output_tools,
        "worker_endpoint": {
            "reachable": bool(advertised_models),
            "advertised_models": advertised_models,
            "requested_model": requested_model,
            "selected_model": selected_model,
            "fallback_supported": True,
        },
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
    progress: Callable[[dict], None] | None = None,
) -> dict:
    confirm = confirm or (
        lambda question: (
            assume_yes or input(f"{question} [Y/n] ").strip().lower() in {"", "y", "yes"}
        )
    )
    progress = progress or (lambda _event: None)
    setup_started = time.perf_counter()
    progress(
        {
            "state": "started",
            "phase": "setup",
            "label": "Inspecting this Mac",
            "progress": 0,
            "total": 5,
            "eta_seconds": None,
        }
    )
    ensure_directories()
    hardware = detect()
    problems = validate_supported(hardware)
    if problems:
        raise RuntimeError("; ".join(problems))
    progress(
        {
            "state": "updated",
            "phase": "setup",
            "label": f"Hardware ready · {hardware.chip}",
            "progress": 1,
            "total": 5,
            "eta_seconds": None,
        }
    )
    actions = []
    if not runtime_executable("spark-mlx-server"):
        if not confirm("Install the pinned Spark MLX runtime and Hugging Face downloader?"):
            raise RuntimeError("Spark runtime installation was declined")
        progress(
            {
                "state": "updated",
                "phase": "runtime",
                "label": "Installing the pinned Spark runtime",
                "progress": 1,
                "total": 5,
                "eta_seconds": 45,
            }
        )
        actions.append({"runtime_command": install_runtime(dry_run=dry_run)})
    progress(
        {
            "state": "updated",
            "phase": "runtime",
            "label": "Spark runtime ready",
            "progress": 2,
            "total": 5,
            "eta_seconds": None,
        }
    )
    model = model_snapshot()
    if not model:
        if not confirm(f"Download {MODEL_REPO} 8-bit (approximately 4.1 GB)?"):
            raise RuntimeError("model download was declined")
        progress(
            {
                "state": "updated",
                "phase": "model",
                "label": "Downloading the 4.1 GB Spark checkpoint",
                "progress": 2,
                "total": 5,
                "eta_seconds": None,
            }
        )
        model = download_model(dry_run=dry_run)
        actions.append({"downloaded_model": str(model)})
    progress(
        {
            "state": "updated",
            "phase": "model",
            "label": "Model checkpoint ready",
            "progress": 3,
            "total": 5,
            "eta_seconds": None,
        }
    )
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
        progress(
            {
                "state": "updated",
                "phase": "server",
                "label": "Loading Spark into unified memory",
                "progress": 3,
                "total": 5,
                "eta_seconds": 30,
            }
        )
        actions.append({"temporary_worker_pid": worker.pid, "log": str(log_path)})
        try:
            wait_for_server(config)
            progress(
                {
                    "state": "updated",
                    "phase": "server",
                    "label": "Spark server is responding",
                    "progress": 4,
                    "total": 5,
                    "eta_seconds": None,
                }
            )
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
                progress=progress,
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
    progress(
        {
            "state": "completed",
            "phase": "setup",
            "label": "Fresnel setup complete",
            "progress": 5,
            "total": 5,
            "eta_seconds": 0,
            "seconds": round(time.perf_counter() - setup_started, 3),
        }
    )
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
