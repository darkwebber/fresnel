from pathlib import Path

from fresnel import integrations
from fresnel.release import homebrew_formula


def test_generic_and_cursor_integrations(tmp_path):
    integrations.install("generic", tmp_path)
    assert (tmp_path / "FRESNEL.md").is_file()
    assert integrations.uninstall("generic", tmp_path)
    integrations.install("cursor", tmp_path)
    assert (tmp_path / ".cursor/rules/fresnel.mdc").is_file()


def test_codex_skill_source_and_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    result = integrations.install("codex", dry_run=True)
    assert result[0]["kind"] == "skill"
    assert integrations.SKILL_SOURCE.joinpath("SKILL.md").is_file()


def test_homebrew_formula_is_pinned():
    formula = homebrew_formula(
        "0.1.0",
        "https://example.test/fresnel.tar.gz",
        "a" * 64,
        homepage="https://example.test/fresnel",
    )
    assert 'version "0.1.0"' in formula
    assert 'sha256 "' + "a" * 64 + '"' in formula
    assert "virtualenv_install_with_resources" in formula
    assert 'homepage "https://example.test/fresnel"' in formula
