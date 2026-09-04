import io
import subprocess

from fresnel.repository import RepositoryIndex
from fresnel.store import Store
from fresnel.terminal import LiveDraft, copy_markdown, render_markdown


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_live_draft_uses_and_restores_alternate_screen():
    output = TTY()
    with LiveDraft(output) as draft:
        draft.write("partial")
        draft.reset("clean")
    assert output.getvalue().startswith("\x1b[?1049h")
    assert output.getvalue().endswith("\x1b[?1049l")


def test_markdown_render_pipeline_and_fallback(monkeypatch):
    stdout = TTY()
    monkeypatch.setattr("fresnel.terminal.sys.stdout", stdout)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(
        "fresnel.terminal.shutil.which", lambda name: f"/bin/{name}" if name in {"termtex", "glow"} else None
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="math" if "termtex" in command[0] else "pretty")

    monkeypatch.setattr("fresnel.terminal.subprocess.run", run)
    result = render_markdown("$x^2$")
    assert result.content == "pretty"
    assert commands[0][1:] == ["-md"]
    assert commands[1][0] == "/bin/glow"

    monkeypatch.setattr("fresnel.terminal.shutil.which", lambda _name: None)
    fallback = render_markdown("raw")
    assert fallback.content == "raw"
    assert "renderer unavailable" in fallback.warning


def test_clipboard_receives_raw_markdown(monkeypatch):
    captured = {}
    monkeypatch.setattr("fresnel.terminal.os.path.isfile", lambda _path: True)
    monkeypatch.setattr(
        "fresnel.terminal.subprocess.run",
        lambda _command, **kwargs: captured.update(kwargs) or subprocess.CompletedProcess([], 0),
    )
    assert copy_markdown("**raw**") == (True, None)
    assert captured["input"] == "**raw**"


def test_repository_index_is_incremental_and_returns_sparse_evidence(tmp_path):
    (tmp_path / "job.py").write_text(
        "def normalize_email(value):\n    return value.strip().lower()\n"
    )
    (tmp_path / "Pipeline.scala").write_text("object Pipeline {\n  def execute = 1\n}\n")
    store = Store(tmp_path / "state.sqlite3")
    index = RepositoryIndex(store, "project", tmp_path)
    first = index.index()
    second = index.index()
    assert first["indexed"] == 2
    assert second["unchanged"] == 2
    assert "normalize_email" in index.repo_map()
    evidence = index.evidence("normalize email")
    assert "job.py" in evidence
    assert "hash=" in evidence
    store.close()
