from pathlib import Path

from fresnel import onboarding
from fresnel.config import Config


def healthy():
    return {
        "hardware": {"chip": "Apple M4 Pro", "memory_bytes": 24 * 1024**3},
        "problems": [],
    }


def test_onboarding_configures_codex_and_service(tmp_path, monkeypatch):
    messages = []
    integrations = []
    saved = []
    monkeypatch.setattr(onboarding, "doctor", healthy)
    monkeypatch.setattr(onboarding, "load_config", lambda: Config(model_path=str(tmp_path)))
    monkeypatch.setattr(onboarding, "save_config", lambda value: saved.append(value))
    monkeypatch.setattr(onboarding, "install_service", lambda _config: tmp_path / "worker.plist")
    monkeypatch.setattr(onboarding, "server_healthy", lambda _host, _port: True)
    monkeypatch.setattr(
        onboarding,
        "install_integration",
        lambda product, project: integrations.append((product, project)) or [{"installed": True}],
    )

    result = onboarding.run_onboarding(
        product="codex", service=True, output=messages.append, color=False
    )

    assert result["completed"] is True
    assert result["server_healthy"] is True
    assert integrations == [("codex", None)]
    assert saved[0].start_at_login is True
    assert any("restart Codex" in line for line in messages)


def test_onboarding_prompts_for_project_in_invalid_choice_loop(tmp_path, monkeypatch):
    answers = iter(["9", "2", str(tmp_path), "n"])
    messages = []
    installed = []
    monkeypatch.setattr(onboarding, "doctor", healthy)
    monkeypatch.setattr(onboarding, "load_config", lambda: Config(model_path=str(tmp_path)))
    monkeypatch.setattr(onboarding, "save_config", lambda _value: None)
    monkeypatch.setattr(onboarding, "server_healthy", lambda _host, _port: False)
    monkeypatch.setattr(
        onboarding,
        "install_integration",
        lambda product, project: installed.append((product, project)) or [],
    )

    result = onboarding.run_onboarding(
        service=False,
        input_fn=lambda _prompt: next(answers),
        output=messages.append,
        color=False,
    )

    assert result["product"] == "cursor"
    assert installed == [("cursor", tmp_path)]
    assert any("Enter a number" in line for line in messages)


def test_onboarding_stops_when_doctor_finds_problem(monkeypatch):
    monkeypatch.setattr(
        onboarding,
        "doctor",
        lambda: {
            "hardware": {"chip": "Apple M4", "memory_bytes": 16 * 1024**3},
            "problems": ["model missing"],
        },
    )
    monkeypatch.setattr(onboarding, "load_config", Config)
    result = onboarding.run_onboarding(output=lambda _line: None, color=False)
    assert result == {"completed": False, "problems": ["model missing"]}


def test_onboarding_project_is_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "doctor", healthy)
    monkeypatch.setattr(onboarding, "load_config", lambda: Config(model_path=str(tmp_path)))
    monkeypatch.setattr(onboarding, "save_config", lambda _value: None)
    monkeypatch.setattr(onboarding, "server_healthy", lambda _host, _port: False)
    monkeypatch.setattr(onboarding, "install_integration", lambda _product, _project: [])
    result = onboarding.run_onboarding(
        product="generic", project=Path(tmp_path), service=False, output=lambda _line: None
    )
    assert result["project"] == str(tmp_path.resolve())
