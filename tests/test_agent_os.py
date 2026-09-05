import json

import pytest

from fresnel.capabilities import CapabilityBroker, discover
from fresnel.config import Config
from fresnel.context import ContextItem, compile_context
from fresnel.engine import run
from fresnel.memory import Memory
from fresnel.protocol import parse_plan
from fresnel.repository import RepositoryIndex
from fresnel.store import Store
from fresnel.workspace import Workspace


def raw_plan(targets=None):
    targets = targets or ["app.py"]
    return {
        "protocol_version": "1.1",
        "objective": "build bounded files",
        "interfaces": ["public functions remain stable"],
        "invariants": ["no external writes"],
        "components": [
            {
                "id": target.removesuffix(".py"),
                "task": f"create {target}",
                "targets": [target],
                "acceptance": ["file compiles"],
                "implementation": ["define a value"],
                "validation": [["python3", "-m", "py_compile", target]],
                "interfaces": [f"{target} is importable"],
                "invariants": ["deterministic"],
                "risk_envelope": {"write_paths": [target], "network": "none"},
                "budgets": {
                    "max_capability_calls": 2,
                    "max_edit_attempts": 3,
                    "wall_seconds": 60,
                },
            }
            for target in targets
        ],
        "integration_validation": [
            ["python3", "-m", "py_compile", *targets]
        ],
    }


def test_protocol_11_is_additive_and_protocol_10_still_parses():
    plan = parse_plan(raw_plan())
    assert plan.protocol_version == "1.1"
    assert plan.components[0].risk.write_paths == ("app.py",)
    assert plan.components[0].budgets.max_capability_calls == 2
    legacy = raw_plan()
    legacy["protocol_version"] = "1.0"
    for key in ("interfaces", "invariants"):
        legacy.pop(key)
    legacy["components"][0].pop("risk_envelope")
    legacy["components"][0].pop("budgets")
    assert parse_plan(legacy).protocol_version == "1.0"


def test_context_compiler_records_inclusions_and_budget_omissions(tmp_path):
    store = Store(tmp_path / "state.db")
    required = ContextItem("state", "required", "current state", "state", 10)
    small = ContextItem("small", "short", "high utility", "small", 5)
    budget = (len(required.render() + "\n\n" + small.render()) + 3) // 4
    rendered, manifest = compile_context(
        store,
        "run",
        "component",
        1,
        budget,
        [required],
        [
            small,
            ContextItem("large", "x" * 100, "too large", "large", 1),
        ],
    )
    assert "required" in rendered and "short" in rendered
    assert any(item.get("reason") == "budget" for item in manifest["items"])
    assert store.connection.execute("SELECT COUNT(*) FROM context_manifests").fetchone()[0] == 1
    store.close()


def test_inferred_memory_requires_opt_in_and_repeated_runs(tmp_path):
    memory = Memory(Store(tmp_path / "state.db"))
    assert memory.observe("style", "concise", run_id="one", source="result") is None
    memory.set_personalization(True)
    assert memory.observe("style", "concise", run_id="one", source="result") is None
    assert memory.observe("style", "concise", run_id="one", source="result") is None
    promoted = memory.observe("style", "concise", run_id="two", source="result")
    assert promoted
    assert memory.profile()[0]["value"]["explicit"] is False
    with pytest.raises(ValueError, match="secrets"):
        memory.remember("api_key", "secret")
    memory.close()


def test_workspace_checkpoint_and_stale_source_detection(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("x = 1\n")
    store = Store(tmp_path / "state.db")
    run_id = store.new_run("test", "spark")
    plan = parse_plan(raw_plan())
    workspace = Workspace.create(store, run_id, "project", source, plan, ("app.py",))
    checkpoint = workspace.checkpoint("app", {"done": []}, {"components": []}, ("app.py",))
    assert workspace.latest_checkpoint()["id"] == checkpoint
    (source / "app.py").write_text("x = 2\n")
    with pytest.raises(RuntimeError, match="source changed"):
        workspace.assert_source_fresh()
    store.close()


def test_workspace_resume_restores_verified_snapshot(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("verified = True\n")
    store = Store(tmp_path / "state.db")
    plan = parse_plan(raw_plan())
    run_id = store.new_run("snapshot", "spark")
    workspace = Workspace.create(store, run_id, "project", source, plan, ("app.py",))
    workspace.checkpoint("app", {}, {"components": []}, ("app.py",))
    (workspace.repo / "app.py").write_text("unverified = True\n")
    workspace.restore_latest()
    assert (workspace.repo / "app.py").read_text() == "verified = True\n"
    assert list((workspace.root / "artifacts").glob("unverified-*/app.py"))
    store.close()


def test_lazy_capability_broker_limits_reads_and_tests(tmp_path):
    (tmp_path / "app.py").write_text("value = 1\n")
    store = Store(tmp_path / "state.db")
    index = RepositoryIndex(store, "project", tmp_path)
    index.index()
    component = parse_plan(raw_plan()).components[0]
    broker = CapabilityBroker(store, "run", component, tmp_path, index)
    assert discover("find a project symbol")
    excerpt = broker.resolve(
        {
            "capability": "file_excerpt",
            "intent": "inspect value",
            "path": "app.py",
            "start_line": 1,
            "end_line": 1,
        }
    )
    assert "value = 1" in excerpt["content"]
    validation = broker.resolve(
        {
            "capability": "test_execution",
            "intent": "compile target",
            "argv": ["python3", "-m", "py_compile", "app.py"],
        }
    )
    assert "exit_code=0" in validation["content"]
    with pytest.raises(ValueError, match="declared validation"):
        broker.resolve(
            {"capability": "test_execution", "intent": "escape", "argv": ["env"]}
        )
    store.close()


def test_capability_turn_does_not_consume_edit_attempt(tmp_path, monkeypatch):
    replies = iter(
        [
            '<<<NEEDS_CAPABILITY>>>{"capability":"discover","intent":"inspect project"}<<<END>>>',
            '<<<CREATE path="app.py">>>\nvalue = 1\n<<<END>>>',
        ]
    )
    monkeypatch.setattr("fresnel.engine.call_worker", lambda *_args, **_kwargs: (next(replies), {}))
    store = Store(tmp_path / "state.db")
    result = run(tmp_path, parse_plan(raw_plan()), Config(), store=store)
    component = result["components"][0]
    assert result["success"] is True, json.dumps(result, indent=2)
    assert len(component["capability_calls"]) == 1
    assert [attempt["attempt"] for attempt in component["attempts"]] == [1, 1]
    store.close()


def test_interrupted_run_resumes_after_last_verified_component(tmp_path, monkeypatch):
    calls = []

    def interrupted(_endpoint, _model, _prompt, *_args, **_kwargs):
        calls.append(len(calls))
        if len(calls) == 1:
            return '<<<CREATE path="a.py">>>\na = 1\n<<<END>>>', {}
        raise KeyboardInterrupt

    monkeypatch.setattr("fresnel.engine.call_worker", interrupted)
    store = Store(tmp_path / "state.db")
    plan = parse_plan(raw_plan(["a.py", "b.py"]))
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, plan, Config(), store=store)
    run_id = store.recent_runs(1)[0]["id"]

    monkeypatch.setattr(
        "fresnel.engine.call_worker",
        lambda *_args, **_kwargs: ('<<<CREATE path="b.py">>>\nb = 2\n<<<END>>>', {}),
    )
    result = run(tmp_path, plan, Config(), store=store, resume_run_id=run_id)
    assert result["success"] is True, json.dumps(result, indent=2)
    assert [item["id"] for item in result["components"]] == ["a", "b"]
    assert "a = 1" in result["diff"] and "b = 2" in result["diff"]
    store.close()
