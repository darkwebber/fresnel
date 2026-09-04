from pathlib import Path

from fresnel import integrations, mcp_server
from fresnel.release import homebrew_formula, termtex_formula
from fresnel.store import Store


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
    assert "fresnel.tar.gz" in formula
    assert 'sha256 "' + "a" * 64 + '"' in formula
    assert "virtualenv_install_with_resources" in formula
    assert 'homepage "https://example.test/fresnel"' in formula
    assert 'depends_on "glow"' in formula
    assert 'depends_on "darkwebber/tap/termtex"' in formula
    assert "e3e21f41b38e9c2f579752dcfd9e23ac4cd15df7" in termtex_formula()


def test_modified_integration_is_preserved_while_missing_one_syncs(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    integrations.install("generic", tmp_path, store=store)
    destination = tmp_path / "FRESNEL.md"
    destination.write_text("my customization\n")
    result = integrations.sync("generic", tmp_path, store=store)
    assert result[0]["action"] == "preserved"
    assert destination.read_text() == "my customization\n"

    destination.unlink()
    result = integrations.sync("generic", tmp_path, store=store)
    assert result[0]["action"] == "updated"
    assert destination.is_file()
    store.close()


def test_opencode_uses_skill_path_and_backs_up_legacy_agent(tmp_path):
    legacy = tmp_path / ".opencode/agents/fresnel.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old adapter")
    store = Store(tmp_path / "state.sqlite3")
    changes = integrations.install("opencode", tmp_path, store=store)
    assert (tmp_path / ".opencode/skills/fresnel/SKILL.md").is_file()
    assert not legacy.exists()
    assert "backup" in changes[-1]
    store.close()


def test_contract_is_versioned_and_exposed_over_mcp():
    contract = integrations.contract_data()
    assert contract["contract_version"] == "0.4.1"
    assert "fresnel_contract" in {tool["name"] for tool in mcp_server.definitions()}
    assert mcp_server.command("fresnel_contract", {}) == [
        "fresnel",
        "contract",
        "--format",
        "json",
    ]
