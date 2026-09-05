import json

from fresnel.config import Config
from fresnel.engine import _sandboxed_command, run
from fresnel.protocol import parse_plan
from fresnel.store import Store
from fresnel.worker import WorkerTruncated


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
    assert result["success"] is True, json.dumps(result, indent=2)
    assert result["applied"] is False
    assert not (tmp_path / "app.py").exists()
    assert result["metrics"]["estimated_coordinator_cost_usd"] == 0.0012
    assert "def add" in result["diff"]
    store.close()


def test_repeated_capability_reuses_evidence_and_bounds_repairs(tmp_path, monkeypatch):
    calls = []
    resolutions = []

    def worker(*_args, **_kwargs):
        calls.append(1)
        payload = {"capability": "discover", "intent": f"inspect context {len(calls)}"}
        return f'<<<NEEDS_CAPABILITY>>>{json.dumps(payload)}<<<END>>>', {}

    def resolve(_self, payload):
        resolutions.append(payload)
        return {"id": "evidence", "source_hash": "abc", "capability": "discover",
                "source": "local", "content": "Use supplied contract."}

    monkeypatch.setattr("fresnel.engine.call_worker", worker)
    monkeypatch.setattr("fresnel.engine.CapabilityBroker.resolve", resolve)
    store = Store(tmp_path / "state.db")
    result = run(tmp_path, plan(), Config(), store=store)
    store.close()
    assert not result["success"]
    assert len(resolutions) == 1
    assert len(calls) == 4  # one reference plus the configured three repair attempts
    attempts = result["components"][0]["attempts"]
    assert sum("repeated capability" in a.get("error", "") for a in attempts) == 3


def test_denied_actions_consume_repair_budget(tmp_path, monkeypatch):
    calls = []

    def worker(*_args, **_kwargs):
        calls.append(1)
        return '<<<REQUEST_ACTION>>>{"kind":"secret","path":".env"}<<<END>>>', {}

    monkeypatch.setattr("fresnel.engine.call_worker", worker)
    monkeypatch.setattr("fresnel.engine.decide", lambda *_a, **_kw: {
        "decision": "deny", "reason": "secret access denied"})
    store = Store(tmp_path / "state.db")
    result = run(tmp_path, plan(), Config(), store=store)
    store.close()
    assert not result["success"]
    assert len(calls) == 3


def test_engine_applies_after_quality_gates(tmp_path, monkeypatch):
    monkeypatch.setattr("fresnel.engine.call_worker", fake_worker)
    store = Store(tmp_path / "state.db")
    result = run(tmp_path, plan(), Config(), store=store, apply=True)
    assert result["success"] is True, json.dumps(result, indent=2)
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
    assert "deny network" in command[2]
    assert "deny file-write" in command[2]
    assert command[-2:] == ["python3", "test.py"]


def test_macos_sandbox_exempts_active_workspace_from_sensitive_parent(
    tmp_path, monkeypatch
):
    workspace = (
        tmp_path
        / "Library"
        / "Application Support"
        / "Fresnel"
        / "workspaces"
        / "run-id"
        / "repo"
    )
    workspace.mkdir(parents=True)
    monkeypatch.setattr("fresnel.sandbox.Path.home", lambda: tmp_path)
    monkeypatch.setattr("fresnel.sandbox.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "fresnel.sandbox.Path.is_file",
        lambda self: str(self) == "/usr/bin/sandbox-exec",
    )

    command = _sandboxed_command(workspace, ("node", "--check", "app.js"))
    profile = command[2]

    sensitive = tmp_path / "Library" / "Application Support" / "Fresnel"
    assert f'(subpath "{sensitive}")' in profile
    assert f'(require-not (subpath "{workspace}"))' in profile
    assert command[-3:] == ["node", "--check", "app.js"]


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
    assert result["success"] is True, json.dumps(result, indent=2)
    assert len(result["components"][0]["attempts"]) == 2
    store.close()


def test_truncated_worker_output_is_never_applied_and_is_retried_compactly(
    tmp_path, monkeypatch
):
    prompts = []

    def worker(_endpoint, _model, prompt, *_args, **_kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            raise WorkerTruncated("<<<CREATE path=\"app.py\">>>\npartial", {"completion_tokens": 9})
        return fake_worker()

    monkeypatch.setattr("fresnel.engine.call_worker", worker)
    monkeypatch.setattr("fresnel.engine.memory_free_percent", lambda: 55)
    store = Store(tmp_path / "truncated.db")
    result = run(tmp_path, plan(), Config(), store=store, apply=True)
    attempts = result["components"][0]["attempts"]
    assert result["success"] is True, json.dumps(result, indent=2)
    assert len(attempts) == 2
    assert attempts[0]["raw_output"].endswith("partial")
    assert attempts[0]["budget"]["max_output_tokens"] == 8192
    assert "Previous output hit the token limit" in prompts[1]
    assert "OVERALL GOAL:\ncreate calculator" in prompts[1]
    assert (tmp_path / "app.py").read_text().startswith("def add")
    assert result["metrics"]["worker_truncation_retries"] == 1
    store.close()


def test_engine_reduces_output_budget_under_memory_pressure(tmp_path, monkeypatch):
    observed = []

    def worker(*args, **kwargs):
        observed.append(args[3])
        return fake_worker()

    monkeypatch.setattr("fresnel.engine.call_worker", worker)
    monkeypatch.setattr("fresnel.engine.memory_free_percent", lambda: 15)
    store = Store(tmp_path / "pressure.db")
    result = run(tmp_path, plan(), Config(), store=store)
    assert result["success"] is True, json.dumps(result, indent=2)
    assert observed == [2048]
    assert result["components"][0]["attempts"][0]["budget"]["pressure"] == "high"
    store.close()


def test_engine_uses_snapshot_model_id_and_emits_structured_progress(tmp_path, monkeypatch):
    models = []
    events = []

    def worker(_endpoint, model, *_args, **_kwargs):
        models.append(model)
        return fake_worker()

    monkeypatch.setattr("fresnel.engine.call_worker", worker)
    store = Store(tmp_path / "progress.db")
    config = Config(model_path="/models/snapshots/revision")
    result = run(tmp_path, plan(), config, store=store, progress=events.append)
    assert result["success"] is True
    assert models == ["/models/snapshots/revision"]
    assert events[0]["phase"] == "workspace"
    assert any(event["phase"] == "worker" for event in events)
    assert any(event["phase"] == "validation" for event in events)
    assert events[-1]["state"] == "completed"
    assert events[-1]["progress"] == events[-1]["total"] == 1
    assert result["progress"] == events
    store.close()
