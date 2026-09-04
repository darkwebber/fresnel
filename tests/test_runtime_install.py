import sys
from pathlib import Path

from fresnel import setup


def test_runtime_install_uses_uv_for_stable_runtime_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(
        setup.shutil, "which", lambda name: "/opt/homebrew/bin/uv" if name == "uv" else None
    )
    monkeypatch.setattr(setup, "runtime_dir", lambda: tmp_path / "runtime")
    commands = setup.install_runtime(dry_run=True)
    assert commands[0][:3] == ["/opt/homebrew/bin/uv", "venv", "--python"]
    assert sys.executable in commands[0]
    assert setup.RUNTIME_REVISION in commands[1][-2]


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
