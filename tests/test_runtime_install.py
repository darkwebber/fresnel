import sys
from pathlib import Path

from fresnel import setup


def test_runtime_install_uses_uv_for_uv_tool_environments(monkeypatch):
    monkeypatch.setattr(
        setup.shutil, "which", lambda name: "/opt/homebrew/bin/uv" if name == "uv" else None
    )
    command = setup.install_runtime(dry_run=True)
    assert command[:4] == ["/opt/homebrew/bin/uv", "pip", "install", "--python"]
    assert sys.executable in command
    assert setup.RUNTIME_REVISION in command[-2]


def test_runtime_executable_prefers_private_homebrew_environment(tmp_path, monkeypatch):
    private_python = tmp_path / "libexec/bin/python"
    private_python.parent.mkdir(parents=True)
    private_python.write_text("")
    server = private_python.parent / "spark-mlx-server"
    server.write_text("#!/bin/sh\n")
    server.chmod(0o755)
    monkeypatch.setattr(setup.sys, "executable", str(private_python))
    monkeypatch.setattr(setup.shutil, "which", lambda _name: None)

    assert setup.runtime_executable("spark-mlx-server") == str(server)
    command = setup.server_command(setup.Config(model_path=str(Path(tmp_path))))
    assert command[0] == str(server)
