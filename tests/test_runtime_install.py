import sys

from fresnel import setup


def test_runtime_install_uses_uv_for_uv_tool_environments(monkeypatch):
    monkeypatch.setattr(
        setup.shutil, "which", lambda name: "/opt/homebrew/bin/uv" if name == "uv" else None
    )
    command = setup.install_runtime(dry_run=True)
    assert command[:4] == ["/opt/homebrew/bin/uv", "pip", "install", "--python"]
    assert sys.executable in command
    assert setup.RUNTIME_REVISION in command[-2]
