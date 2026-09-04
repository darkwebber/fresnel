from fresnel.config import Config
from fresnel.engine import _sandboxed_command, run
from fresnel.protocol import parse_plan
from fresnel.store import Store


def plan():
    return parse_plan(
        {
            "protocol_version": "1.0",
            "objective": "create calculator",
            "contracts": [
                {
                    "path": "test_contract.py",
                    "content": "from app import add\nassert add(2, 3) == 5\n",
                }
            ],
            "components": [
                {
                    "id": "calculator",
                    "task": "create add",
                    "depends_on": [],
                    "targets": ["app.py"],
                    "context": ["test_contract.py"],
                    "constraints": ["no dependencies"],
                    "acceptance": ["2 + 3 is 5"],
                    "implementation": ["define add(a, b) returning a + b"],
                    "validation": [["python3", "test_contract.py"]],
                    "references": {"local_docs": [], "help_commands": [], "web_queries": []},
                }
            ],
            "integration_validation": [["python3", "test_contract.py"]],
            "review_checklist": ["simple implementation"],
        }
    )


def fake_worker(*_args, **_kwargs):
    return '<<<CREATE path="app.py">>>\ndef add(a, b):\n    return a + b\n<<<END>>>', {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": 10},
    }


def test_engine_validates_without_applying(tmp_path, monkeypatch):
    monkeypatch.setattr("fresnel.engine.call_worker", fake_worker)
    store = Store(tmp_path / "state.db")
    config = Config(
        coordinator_input_cost_per_million=1,
        coordinator_output_cost_per_million=2,
    )
    result = run(
        tmp_path,
        plan(),
        config,
        store=store,
        coordinator_calls=[{"usage": {"prompt_tokens": 1000, "completion_tokens": 100}}],
    )
    assert result["success"] is True, result
    assert result["applied"] is False
    assert not (tmp_path / "app.py").exists()
    assert result["metrics"]["estimated_coordinator_cost_usd"] == 0.0012
    assert "def add" in result["diff"]
    store.close()


def test_engine_applies_after_quality_gates(tmp_path, monkeypatch):
    monkeypatch.setattr("fresnel.engine.call_worker", fake_worker)
    store = Store(tmp_path / "state.db")
    result = run(tmp_path, plan(), Config(), store=store, apply=True)
    assert result["success"] is True, result
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text().startswith("def add")
    assert (tmp_path / "test_contract.py").is_file()
    store.close()


def test_macos_validation_is_sandboxed(tmp_path, monkeypatch):
    monkeypatch.setattr("fresnel.engine.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "fresnel.engine.Path.is_file", lambda self: str(self) == "/usr/bin/sandbox-exec"
    )
    command = _sandboxed_command(tmp_path, ("python3", "test.py"))
    assert command[:2] == ["/usr/bin/sandbox-exec", "-p"]
    assert "deny default" in command[2]
    assert command[-2:] == ["python3", "test.py"]


def test_operation_error_is_repaired_within_attempt_budget(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("def add(a, b):\n    return 0\n")
    attempts = iter(
        [
            ('<<<CREATE path="outside.py">>>\nbad\n<<<END>>>', {}),
            (
                '<<<EDIT path="app.py">>><<<SEARCH>>>\ndef add(a, b):\n    return 0\n\n<<<REPLACE>>>\ndef add(a, b):\n    return a + b\n\n<<<END>>>',
                {},
            ),
        ]
    )
    monkeypatch.setattr("fresnel.engine.call_worker", lambda *_args, **_kwargs: next(attempts))
    raw = {
        "protocol_version": "1.0",
        "objective": "repair",
        "contracts": [],
        "components": [
            {
                "id": "repair",
                "task": "repair",
                "depends_on": [],
                "targets": ["app.py"],
                "context": [],
                "constraints": [],
                "acceptance": ["imports"],
                "implementation": ["return a+b"],
                "validation": [["python3", "-m", "py_compile", "app.py"]],
                "references": {"local_docs": [], "help_commands": [], "web_queries": []},
            }
        ],
        "integration_validation": [["python3", "-m", "py_compile", "app.py"]],
        "review_checklist": [],
    }
    store = Store(tmp_path / "repair.db")
    result = run(tmp_path, parse_plan(raw), Config(), store=store)
    assert result["success"] is True, result
    assert len(result["components"][0]["attempts"]) == 2
    store.close()
