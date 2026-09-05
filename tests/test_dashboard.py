"""Accessibility regression coverage for dashboard.render (issue #5).

dashboard.render() prints a plain-text status view and only falls back to a
native Swift UI when one is available on PATH. These tests exercise the
plain-text branch only, so no runtime or model download is required.
"""

import io

from fresnel import dashboard


class _FakeTTY(io.StringIO):
  def isatty(self):
    return True


def _model(**overrides):
  base = {
    "healthy": True,
    "worker": "ready",
    "chip": "Apple M2",
    "memory_free_percent": 42,
    "profile": "balanced",
    "runs": [],
  }
  base.update(overrides)
  return base


def test_render_emits_color_on_a_real_terminal_without_no_color(monkeypatch):
  monkeypatch.delenv("NO_COLOR", raising=False)
  monkeypatch.setattr(dashboard.shutil, "which", lambda _name: None)
  stream = _FakeTTY()
  monkeypatch.setattr(dashboard.sys, "stdout", stream)
  dashboard.render(_model())
  output = stream.getvalue()
  assert "\x1b[" in output
  assert "healthy" in output


def test_render_respects_no_color_even_on_a_real_terminal(monkeypatch):
  monkeypatch.setenv("NO_COLOR", "1")
  monkeypatch.setattr(dashboard.shutil, "which", lambda _name: None)
  stream = _FakeTTY()
  monkeypatch.setattr(dashboard.sys, "stdout", stream)
  dashboard.render(_model())
  output = stream.getvalue()
  assert "\x1b[" not in output
  assert "healthy" in output
  assert "42% memory free" in output
  assert "balanced profile" in output


def test_render_has_no_color_when_stdout_is_not_a_tty(monkeypatch):
  monkeypatch.delenv("NO_COLOR", raising=False)
  monkeypatch.setattr(dashboard.shutil, "which", lambda _name: None)
  stream = io.StringIO()
  monkeypatch.setattr(dashboard.sys, "stdout", stream)
  dashboard.render(_model(worker="idle", memory_free_percent=8, profile="eco"))
  output = stream.getvalue()
  assert "\x1b[" not in output
  assert "idle" in output
  assert "8% memory free" in output
  assert "eco profile" in output


def test_render_lists_recent_tasks_without_color_contamination(monkeypatch):
  monkeypatch.setenv("NO_COLOR", "1")
  monkeypatch.setattr(dashboard.shutil, "which", lambda _name: None)
  stream = _FakeTTY()
  monkeypatch.setattr(dashboard.sys, "stdout", stream)
  dashboard.render(
  _model(
  runs=[{"id": "abcdef1234567890", "status": "COMPLETED", "request": "add a helper"}]
  )
  )
  output = stream.getvalue()
  assert "\x1b[" not in output
  assert "abcdef12" in output
  assert "COMPLETED" in output
