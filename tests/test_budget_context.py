import pytest

from fresnel.budget import allocate
from fresnel.config import Profile
from fresnel.protocol import parse_plan
from fresnel.references import file_excerpt_reference
from fresnel.worker import estimate_prompt_tokens, render_prompt
from fresnel.context import ContextItem


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


def test_context_budget_counts_rendered_metadata(tmp_path):
    from fresnel.store import Store
    store = Store(tmp_path / "state.db")
    item = ContextItem("required", "x" * 40, "required", "source")
    # The raw content fits, but its rendered header must also fit.
    with pytest.raises(ValueError, match="required component context exceeds"):
        from fresnel.context import compile_context

        compile_context(
            store,
            "run",
            "component",
            1,
            item.tokens,
            [item],
            [],
        )


def test_final_prompt_estimate_counts_all_rendered_sections():
    prompt = "goal\n\nconstraints\n\nfiles"
    assert estimate_prompt_tokens(prompt) == max(1, (len(prompt) + 3) // 4)
