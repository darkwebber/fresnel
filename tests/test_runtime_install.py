import sys
from pathlib import Path

from fresnel import setup


def test_runtime_install_uses_prebuilt_wheel_for_stable_runtime_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(setup, "runtime_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr(setup, "cache_dir", lambda: tmp_path / "cache")
    commands = setup.install_runtime(dry_run=True)
    assert commands[0][1:3] == ["-m", "venv"]
    assert sys.executable in commands[0]
    assert commands[1][1:4] == ["-m", "pip", "install"]
    assert any(
        value.endswith("spark_mlx_llm-0.1.0-py3-none-any.whl") for value in commands[1]
    )
    assert "--only-binary=:all:" in commands[1]


def test_runtime_executable_prefers_private_homebrew_environment(tmp_path, monkeypatch):
    private_python = tmp_path / "libexec/bin/python"
    private_python.parent.mkdir(parents=True)
    private_python.write_text("")
    server = private_python.parent / "spark-mlx-server"
    server.write_text("#!/bin/sh\n")
    server.chmod(0o755)
    monkeypatch.setattr(setup.sys, "executable", str(private_python))
    monkeypatch.setattr(setup, "runtime_dir", lambda: tmp_path / "missing-runtime")
    monkeypatch.setattr(setup.shutil, "which", lambda _name: None)

    assert setup.runtime_executable("spark-mlx-server") == str(server)
    command = setup.server_command(setup.Config(model_path=str(Path(tmp_path))))
    assert command[0] == str(server)
