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
