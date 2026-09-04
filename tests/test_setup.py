import hashlib
import io
import json
from pathlib import Path

from fresnel import setup
from fresnel.config import Config


def test_available_port_and_server_command(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "runtime_executable", lambda _name: "spark-mlx-server")
    port = setup.available_port(18081)
    assert port >= 18081
    command = setup.server_command(Config(model_path=str(tmp_path)))
    assert command[0] == "spark-mlx-server"
    assert "--prompt-cache-bytes" in command
    assert '{"enable_thinking":false}' in command


def test_runtime_install_uses_upgrade_stable_application_support(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(setup, "runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr(setup, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(setup, "_download_verified", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup.subprocess, "run", lambda command, **_kwargs: commands.append(command))
    monkeypatch.setattr(setup, "runtime_executable", lambda _name: "/stable/spark-mlx-server")
    setup.install_runtime()
    assert commands[0] == [
        setup.sys.executable,
        "-m",
        "venv",
        str(tmp_path / "runtime"),
    ]
    assert commands[1][:4] == [
        str(tmp_path / "runtime/bin/python"),
        "-m",
        "pip",
        "install",
    ]


def test_model_snapshot_requires_weights(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = (
        tmp_path
        / ".cache/huggingface/hub/models--abenzerps--Spark-X2.5-4B-MLX-8bit/snapshots/92537e99b1c494443ad8e5eea93a2d45f4622a13"
    )
    root.mkdir(parents=True)
    (root / "config.json").write_text("{}")
    (root / "tokenizer.json").write_text("{}")
    assert setup.model_snapshot() is None
    (root / "model.safetensors").write_text("weights")
    assert setup.model_snapshot() == root


def test_doctor_reports_optional_output_helpers_without_becoming_unhealthy(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(setup, "detect", lambda: type("Hardware", (), {
        "thermal_state": "nominal",
        "json": lambda self: {},
    })())
    monkeypatch.setattr(setup, "validate_supported", lambda _hardware: [])
    monkeypatch.setattr(setup, "load_config", lambda: Config(model_path=str(tmp_path)))
    monkeypatch.setattr(setup, "runtime_executable", lambda _name: "/bin/server")
    monkeypatch.setattr(setup, "model_snapshot", lambda: None)
    monkeypatch.setattr(setup, "memory_free_percent", lambda: 80)
    monkeypatch.setattr(setup.shutil, "which", lambda _name: None)
    result = setup.doctor()
    assert result["healthy"] is True
    assert result["output_tools"]["glow"] is None
    assert any("terminal output helpers" in warning for warning in result["warnings"])


def test_server_models_reads_advertised_ids(monkeypatch):
    class Response:
        def __enter__(self):
            return io.BytesIO(json.dumps({"data": [{"id": "/snapshot/model"}]}).encode())

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(setup.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    assert setup.server_models("127.0.0.1", 8081) == ["/snapshot/model"]


def test_launch_agent_is_socket_activated_not_keepalive(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "run_dir", lambda: tmp_path / "run")
    monkeypatch.setattr(setup, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(setup.shutil, "which", lambda _name: "/bin/fresnel-supervisor")
    plist = setup.render_launch_agent(Config())
    assert "<key>Sockets</key>" in plist
    assert "control.sock" in plist
    assert "KeepAlive" not in plist
    assert "RunAtLoad" not in plist


def test_verified_download_resumes_and_publishes_atomically(tmp_path, monkeypatch):
    payload = b"complete-wheel"
    destination = tmp_path / "runtime.whl"
    destination.with_suffix(".whl.part").write_bytes(payload[:8])

    class Response(io.BytesIO):
        status = 206

        def __init__(self, value):
            super().__init__(value)
            self.headers = {"Content-Length": str(len(payload) - 8)}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    requests = []

    def open_request(request, **_kwargs):
        requests.append(request)
        return Response(payload[8:])

    monkeypatch.setattr(setup.urllib.request, "urlopen", open_request)
    result = setup._download_verified(
        "https://example.invalid/runtime.whl",
        destination,
        hashlib.sha256(payload).hexdigest(),
    )
    assert result.read_bytes() == payload
    assert requests[0].get_header("Range") == "bytes=8-"
    assert not destination.with_suffix(".whl.part").exists()
