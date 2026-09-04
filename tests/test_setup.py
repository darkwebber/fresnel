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
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(setup.subprocess, "run", lambda command, **_kwargs: commands.append(command))
    monkeypatch.setattr(setup, "runtime_executable", lambda _name: "/stable/spark-mlx-server")
    setup.install_runtime()
    assert commands[0] == [
        "/bin/uv",
        "venv",
        "--python",
        setup.sys.executable,
        str(tmp_path / "runtime"),
    ]
    assert commands[1][3:5] == ["--python", str(tmp_path / "runtime/bin/python")]


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
