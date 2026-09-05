"""Regression coverage for rendered context budget boundaries."""

import json

import pytest

from fresnel.context import ContextItem, compile_context
from fresnel.store import Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "context.db")
    yield value
    value.close()


def test_exact_fit_includes_optional_and_one_token_short_omits_it(store):
    required = ContextItem("goal", "preserve invariants", "mandatory", "project-a")
    evidence = ContextItem("evidence", "x" * 20, "relevant", "project-a/file")
    expected = required.render() + "\n\n" + evidence.render()
    budget = (len(expected) + 3) // 4

    rendered, manifest = compile_context(store, "r", "c", 1, budget, [required], [evidence])
    assert rendered == expected
    assert manifest["used_tokens"] == budget
    assert all(row["included"] for row in manifest["items"])

    rendered, manifest = compile_context(store, "r", "c", 2, budget - 1, [required], [evidence])
    assert rendered == required.render()
    assert manifest["items"][-1]["reason"] == "budget"
    assert not manifest["items"][-1]["included"]


def test_empty_and_oversized_evidence_are_not_included(store):
    required = ContextItem("goal", "retain objective", "mandatory", "project-a")
    oversized = ContextItem("evidence", "x" * 400, "large", "project-a/large")

    rendered, empty_manifest = compile_context(
        store,
        "r",
        "c",
        1,
        required.rendered_tokens,
        [required],
        [ContextItem("evidence", " ", "empty", "project-a/empty")],
    )
    assert rendered == required.render()
    assert len(empty_manifest["items"]) == 1

    rendered, manifest = compile_context(
        store, "r", "c", 2, required.rendered_tokens, [required], [oversized]
    )
    assert rendered == required.render()
    assert manifest["items"][-1]["reason"] == "budget"
    saved = store.connection.execute(
        "SELECT items_json FROM context_manifests WHERE id=?", (manifest["id"],)
    ).fetchone()[0]
    assert json.loads(saved) == manifest["items"]


def test_required_overflow_raises_without_writing_a_manifest(store):
    item = ContextItem("goal", "mandatory objective", "mandatory", "project-a")

    with pytest.raises(ValueError, match="required component context exceeds"):
        compile_context(store, "r", "c", 1, item.rendered_tokens - 1, [item], [])

    assert store.connection.execute("SELECT COUNT(*) FROM context_manifests").fetchone()[0] == 0
