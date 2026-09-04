import pytest

from fresnel.protocol import parse_plan, safe_path
from fresnel.worker import apply_operations, parse, render_prompt


def raw_plan():
    return {
        "protocol_version": "1.0",
        "objective": "add feature",
        "contracts": [{"path": "tests/test_contract.py", "content": "assert True\n"}],
        "components": [
            {
                "id": "core",
                "task": "implement",
                "depends_on": [],
                "targets": ["app.py"],
                "context": [],
                "constraints": ["pure"],
                "acceptance": ["works"],
                "implementation": ["return 1"],
                "validation": [["python3", "tests/test_contract.py"]],
                "references": {"local_docs": [], "help_commands": [], "web_queries": []},
            }
        ],
        "integration_validation": [["python3", "tests/test_contract.py"]],
        "review_checklist": ["API preserved"],
    }


def test_plan_parses_and_rejects_contract_target():
    plan = parse_plan(raw_plan())
    assert plan.components[0].targets == ("app.py",)
    bad = raw_plan()
    bad["components"][0]["targets"] = ["tests/test_contract.py"]
    with pytest.raises(ValueError, match="contracts"):
        parse_plan(bad)


def test_plan_rejects_forward_dependency_and_major_version():
    bad = raw_plan()
    bad["components"][0]["depends_on"] = ["later"]
    with pytest.raises(ValueError, match="unsatisfied"):
        parse_plan(bad)
    bad = raw_plan()
    bad["protocol_version"] = "2.0"
    with pytest.raises(ValueError, match="unsupported"):
        parse_plan(bad)


def test_safe_path_blocks_escape(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        safe_path(tmp_path, "../secret")
    with pytest.raises(ValueError, match="absolute"):
        safe_path(tmp_path, "/tmp/file")


def test_plan_rejects_path_escape_before_execution():
    bad = raw_plan()
    bad["components"][0]["targets"] = ["../app.py"]
    with pytest.raises(ValueError, match="repository-relative"):
        parse_plan(bad)


def test_worker_parse_and_bounded_apply(tmp_path):
    (tmp_path / "app.py").write_text("VALUE = 1\n")
    response = """<<<EDIT path="app.py">>><<<SEARCH>>>
VALUE = 1

<<<REPLACE>>>
VALUE = 2

<<<END>>>"""
    kind, operations = parse(response)
    assert kind == "operations"
    apply_operations(tmp_path, {"app.py"}, operations)
    assert (tmp_path / "app.py").read_text() == "VALUE = 2\n"
    with pytest.raises(ValueError, match="non-target"):
        apply_operations(
            tmp_path, {"app.py"}, [{"kind": "create", "path": "oops.py", "content": ""}]
        )


def test_worker_special_requests_and_prompt(tmp_path):
    kind, payload = parse('<<<NEEDS_REFERENCE>>>{"kind":"local_docs","query":"json"}<<<END>>>')
    assert (kind, payload["query"]) == ("reference", "json")
    component = parse_plan(raw_plan()).components[0]
    prompt = render_prompt(component, tmp_path)
    assert "FILE DOES NOT EXIST" in prompt
    assert "do not redesign" in prompt


def test_worker_rejects_prose_and_ambiguous_search(tmp_path):
    with pytest.raises(ValueError, match="invalid"):
        parse("Here is your code")
    (tmp_path / "app.py").write_text("x\nx\n")
    with pytest.raises(ValueError, match="exactly once"):
        apply_operations(
            tmp_path,
            {"app.py"},
            [{"kind": "edit", "path": "app.py", "search": "x", "replace": "y"}],
        )


def test_declared_small_file_can_use_compatibility_replacement(tmp_path):
    (tmp_path / "app.py").write_text("old\n")
    apply_operations(
        tmp_path,
        {"app.py"},
        [{"kind": "create", "path": "app.py", "content": "new\n"}],
        replace_existing_create=True,
    )
    assert (tmp_path / "app.py").read_text() == "new\n"


def test_single_python_target_accepts_syntax_checked_fallback():
    kind, operations = parse("```python\ndef value():\n    return 1\n```", fallback_target="app.py")
    assert kind == "operations"
    assert operations[0]["path"] == "app.py"
    with pytest.raises(ValueError, match="invalid"):
        parse("Here is an explanation, not code.", fallback_target="app.py")
    with pytest.raises(ValueError, match="invalid"):
        parse('{"REQUEST_ACTION": "UNKNOWN"}', fallback_target="app.py")


def test_exact_replace_json_compatibility():
    payload = '{"REQUEST_ACTION":"REPLACE","path":"app.py","SEARCH":"old","REPLACE":"new"}'
    kind, operations = parse(payload, fallback_target="app.py")
    assert kind == "operations"
    assert operations[0]["search"] == "old"
    lower = '{"request_type":"REQUEST_ACTION","action":"REPLACE","path":"app.py","search":"old","replace":"new"}'
    assert parse(lower, fallback_target="app.py")[1][0]["replace"] == "new"
    generic_path = '{"request":"REQUEST_ACTION","file":"app.py","path":"relative.py","search":"old","replace":"new"}'
    assert parse(generic_path, fallback_target="app.py")[0] == "operations"


def test_edit_markers_allow_code_immediately_after_delimiter():
    response = '<<<EDIT path="app.py">>><<<SEARCH>>>old\n<<<REPLACE>>>new\n<<<END>>>'
    assert parse(response)[1][0]["search"] == "old"


def test_loose_replace_marker_compatibility():
    response = "<<<REQUEST_ACTION>>>\nSEARCH\nold\nREPLACE\nnew\nEND\n<<<"
    kind, operations = parse(response, fallback_target="app.py")
    assert kind == "operations"
    assert operations[0]["replace"] == "new"
    assert (
        parse(
            response.replace("<<<REQUEST_ACTION>>>", "<<<REQUEST_ACTION>>"),
            fallback_target="app.py",
        )[0]
        == "operations"
    )
