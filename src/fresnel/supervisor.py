"""On-demand launchd socket client and worker lifecycle supervisor for macOS."""

from __future__ import annotations

import ctypes
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from .config import Config, load_config, logs_dir, run_dir
from .hardware import detect, memory_free_percent

SOCKET_NAME = "Control"


def _worker_environment() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "MLX_METAL_CACHE_DIR",
        "PYTHONUNBUFFERED",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def socket_path() -> Path:
    return run_dir() / "control.sock"


def _request(payload: dict[str, Any], timeout: float = 190) -> dict[str, Any]:
    deadline = time.monotonic() + min(timeout, 10)
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(timeout)
                client.connect(str(socket_path()))
                client.sendall(json.dumps(payload).encode() + b"\n")
                data = bytearray()
                while not data.endswith(b"\n"):
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    data.extend(chunk)
                return json.loads(data or b"{}")
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"Fresnel worker supervisor did not respond: {last_error}")


def acquire(run_id: str, *, timeout: float = 190) -> dict[str, Any]:
    return _request({"operation": "acquire", "run_id": run_id}, timeout)


def release(run_id: str) -> dict[str, Any]:
    return _request({"operation": "release", "run_id": run_id}, 5)


def status() -> dict[str, Any]:
    return _request({"operation": "status"}, 5)


@contextmanager
def lease(identifier: str):
    """Acquire the managed worker when installed, otherwise preserve direct-server behavior."""
    managed = socket_path().exists()
    result = {"managed": managed, "state": "external"}
    if managed:
        result = {"managed": True, **acquire(identifier)}
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "worker supervisor refused the request"))
    try:
        yield result
    finally:
        if managed:
            with suppress(Exception):
                release(identifier)


def _launchd_socket() -> socket.socket:
    libc = ctypes.CDLL("/usr/lib/system/libsystem_c.dylib")
    activate = libc.launch_activate_socket
    activate.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_int)),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    activate.restype = ctypes.c_int
    descriptors = ctypes.POINTER(ctypes.c_int)()
    count = ctypes.c_size_t()
    error = activate(SOCKET_NAME.encode(), ctypes.byref(descriptors), ctypes.byref(count))
    if error or count.value != 1:
        raise RuntimeError(f"launchd socket activation failed: error={error} count={count.value}")
    return socket.socket(fileno=os.dup(descriptors[0]))


def _healthy(config: Config) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://{config.host}:{config.port}/v1/models", timeout=1
        ) as response:
            return response.status == 200
    except Exception:
        return False


def _worker_command() -> list[str]:
    completed = subprocess.run(
        ["fresnel", "internal-server-command"],
        text=True,
        capture_output=True,
        check=True,
    )
    return list(json.loads(completed.stdout)["command"])


def serve() -> None:
    """Serve lease requests; launchd starts this process only when the socket is used."""
    config = load_config()
    listener = _launchd_socket()
    listener.settimeout(1)
    worker: subprocess.Popen | None = None
    leases: set[str] = set()
    last_release = time.monotonic()
    load_started: float | None = None
    stopping = False

    def stop(_signal=None, _frame=None):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        hardware = detect()
        idle_limit = (
            config.idle_seconds_battery if hardware.power_source == "battery" else config.idle_seconds_ac
        )
        free = memory_free_percent()
        if worker and not leases and (
            time.monotonic() - last_release >= idle_limit or (free is not None and free < 12)
        ):
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
            worker = None
            load_started = None
        if not worker and not leases and time.monotonic() - last_release >= max(5, idle_limit):
            break
        try:
            connection, _address = listener.accept()
        except TimeoutError:
            continue
        with connection:
            request = json.loads(connection.makefile("r").readline())
            operation = request.get("operation")
            if operation == "acquire":
                if free is not None and free < 20:
                    response = {
                        "ok": False,
                        "error": "memory pressure is too high to load Spark",
                        "memory_free_percent": free,
                        "recommendation": "close memory-heavy apps or select the eco profile",
                    }
                else:
                    run_id = str(request["run_id"])
                    if not worker or worker.poll() is not None:
                        logs_dir().mkdir(parents=True, exist_ok=True)
                        log = (logs_dir() / "worker.log").open("a")
                        worker = subprocess.Popen(
                            _worker_command(),
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            env=_worker_environment(),
                        )
                        load_started = time.monotonic()
                        deadline = time.monotonic() + 180
                        while time.monotonic() < deadline and not _healthy(config):
                            if worker.poll() is not None:
                                break
                            time.sleep(0.25)
                    if _healthy(config):
                        leases.add(run_id)
                        response = {
                            "ok": True,
                            "state": "ready",
                            "reused": bool(load_started and time.monotonic() - load_started > 1),
                            "load_seconds": round(time.monotonic() - load_started, 3)
                            if load_started
                            else 0,
                            "leases": len(leases),
                        }
                    else:
                        response = {"ok": False, "error": "Spark failed to become healthy"}
            elif operation == "release":
                leases.discard(str(request.get("run_id", "")))
                last_release = time.monotonic()
                response = {"ok": True, "leases": len(leases), "idle_seconds": idle_limit}
            elif operation == "status":
                response = {
                    "ok": True,
                    "state": "ready" if worker and _healthy(config) else "idle",
                    "leases": len(leases),
                    "memory_free_percent": free,
                    "power_source": hardware.power_source,
                    "thermal_state": hardware.thermal_state,
                }
            else:
                response = {"ok": False, "error": "unknown supervisor operation"}
            connection.sendall(json.dumps(response).encode() + b"\n")
    if worker and not leases:
        worker.terminate()
