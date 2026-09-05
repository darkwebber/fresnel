import pytest

from fresnel.budget import allocate
from fresnel.config import Profile
from fresnel.protocol import parse_plan
from fresnel.references import file_excerpt_reference
from fresnel.worker import render_prompt
from fresnel.context import ContextItem, compile_context
from fresnel.store import Store


def _component():
    raw = {
        "protocol_version": "1.0",
        "objective": "retain the overall goal",
        "contracts": [],
        "components": [
            {
                "id": "bounded",
                "task": "change the selected function",
                "depends_on": [],
                "targets": ["large.py"],
                "context": ["contract.txt"],
                "constraints": ["preserve the API"],
                "acceptance": ["the contract passes"],
                "implementation": ["use an exact replacement"],
                "validation": [["python3", "large.py"]],
                "references": {"local_docs": [], "help_commands": [], "web_queries": []},
            }
        ],
        "integration_validation": [["python3", "large.py"]],
        "review_checklist": [],
    }
    return parse_plan(raw).components[0]


def test_budget_reserves_output_and_reacts_to_pressure_and_retries():
    profile = Profile()
    normal = allocate(profile, estimated_input_tokens=4_000, memory_free_percent=50)
    pressured = allocate(profile, estimated_input_tokens=4_000, memory_free_percent=15)
    retry = allocate(profile, estimated_input_tokens=4_000, memory_free_percent=50, attempt=3)
    assert normal.max_output_tokens == 8192
    assert pressured.pressure == "high"
    assert pressured.max_output_tokens <= 2048
    assert pressured.max_input_tokens < normal.max_input_tokens
    assert retry.max_input_tokens < normal.max_input_tokens


def test_prompt_compacts_files_but_restates_goal_and_excerpt_contract(tmp_path):
    (tmp_path / "large.py").write_text("\n".join(f"line_{n} = {n}" for n in range(4000)))
    (tmp_path / "contract.txt").write_text("expected behavior\n")
    prompt = render_prompt(
        _component(),
        tmp_path,
        goal="retain the overall goal",
        max_input_tokens=2048,
        response_budget=1024,
        attempt=2,
    )
    assert "OVERALL GOAL:\nretain the overall goal" in prompt
    assert "ACCEPTANCE:\n- the contract passes" in prompt
    assert "characters omitted from large.py" in prompt
    assert '"kind":"file_excerpt"' in prompt
    assert len(prompt) < 2048 * 4


def test_file_excerpt_is_bounded_to_declared_context(tmp_path):
    (tmp_path / "large.py").write_text("one\ntwo\nthree\n")
    result = file_excerpt_reference(
        tmp_path,
        {"path": "large.py", "start_line": 2, "end_line": 3},
        {"large.py"},
    )
    assert result["content"] == "two\nthree"
    with pytest.raises(ValueError, match="outside declared context"):
        file_excerpt_reference(tmp_path, {"path": "secret.py"}, {"large.py"})
    with pytest.raises(ValueError, match="1-400 lines"):
        file_excerpt_reference(
            tmp_path,
            {"path": "large.py", "start_line": 1, "end_line": 401},
            {"large.py"},
        )


def _store(tmp_path):
    return Store(tmp_path / "state.sqlite3")


def test_compile_context_with_no_evidence_returns_empty_manifest(tmp_path):
    store = _store(tmp_path)
    rendered, manifest = compile_context(
    store, "run-1", "bounded", 1, 64, [], []
    )
    assert rendered == ""
    assert manifest["used_tokens"] == 0
    assert manifest["items"] == []


def test_compile_context_includes_optional_evidence_that_exactly_fits(tmp_path):
    store = _store(tmp_path)
    objective = ContextItem(kind="objective", content="x" * 8, reason="mandatory", source="plan")
    fitting = ContextItem(kind="file_excerpt", content="y" * 8, reason="context", source="a.py")
    budget = objective.tokens + fitting.tokens
    rendered, manifest = compile_context(
    store, "run-1", "bounded", 1, budget, [objective], [fitting]
    )
    assert manifest["used_tokens"] == budget
    assert all(item["included"] for item in manifest["items"])
    included_sources = {item["source"] for item in manifest["items"]}
    assert included_sources == {"plan", "a.py"}
    assert "a.py" in rendered


def test_compile_context_omits_single_oversized_optional_card(tmp_path):
    store = _store(tmp_path)
    objective = ContextItem(kind="objective", content="x" * 8, reason="mandatory", source="plan")
    oversized = ContextItem(
    kind="file_excerpt", content="z" * 400, reason="context", source="huge.py"
    )
    budget = objective.tokens + 1
    rendered, manifest = compile_context(
    store, "run-1", "bounded", 1, budget, [objective], [oversized]
    )
    omitted = [item for item in manifest["items"] if not item["included"]]
    assert len(omitted) == 1
    assert omitted[0]["source"] == "huge.py"
    assert omitted[0]["reason"] == "budget"
    assert "huge.py" not in rendered


def test_compile_context_surfaces_insufficient_mandatory_budget(tmp_path):
    store = _store(tmp_path)
    objective = ContextItem(kind="objective", content="x" * 400, reason="mandatory", source="plan")
    with pytest.raises(ValueError, match="exceeds the input token budget"):
        compile_context(store, "run-1", "bounded", 1, 1, [objective], [])



def test_compile_context_rejects_stale_required_context(tmp_path):
    store = _store(tmp_path)
    stale = ContextItem(kind="invariant", content="must hold", reason="mandatory", source="plan", fresh=False)
    with pytest.raises(ValueError, match="required context is stale"):
        compile_context(store, "run-1", "bounded", 1, 64, [stale], [])


def test_compile_context_reduced_memory_profile_forces_more_omissions(tmp_path):
    store = _store(tmp_path)
    profile = Profile()
    normal_budget = allocate(profile, estimated_input_tokens=0, memory_free_percent=50).max_input_tokens
    critical_budget = allocate(profile, estimated_input_tokens=0, memory_free_percent=10).max_input_tokens
    assert critical_budget < normal_budget
    objective = ContextItem(kind="objective", content="x" * 8, reason="mandatory", source="plan")
    optional_items = [
    ContextItem(kind="file_excerpt", content="y" * 4000, reason="context", source=f"f{i}.py")
    for i in range(15)
    ]
    _, normal_manifest = compile_context(
    store, "run-1", "bounded", 1, normal_budget, [objective], optional_items
    )
    _, critical_manifest = compile_context(
    store, "run-2", "bounded", 1, critical_budget, [objective], optional_items
    )
    assert all(item["included"] for item in normal_manifest["items"])
    critical_omitted = [item for item in critical_manifest["items"] if not item["included"]]
    assert critical_omitted
    assert all(item["reason"] == "budget" for item in critical_omitted)
