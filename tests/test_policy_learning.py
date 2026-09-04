from fresnel.approvals import classify, decide, request_id
from fresnel.learning import classify_failure, propose, signature
from fresnel.store import Store


def test_approval_policy_and_stable_ids():
    request = {"kind": "install_dependency", "name": "pandas"}
    assert classify(request)[0] == "escalate"
    assert request_id("one", request) == request_id("one", request)
    result = decide("one", request, {request_id("one", request): "approve"})
    assert result["decision"] == "approve"
    assert classify({"kind": "read_secret"})[0] == "deny"
    denied = {"kind": "read_secret"}
    assert decide("one", denied, {request_id("one", denied): "approve"})["decision"] == "deny"
    assert (
        classify({"kind": "exa", "include_domains": ["docs.python.org"]}, web_authorized=True)[0]
        == "approve"
    )


def test_learning_requires_repetition_across_runs(tmp_path):
    store = Store(tmp_path / "state.db")
    category = classify_failure("SyntaxError at line 5")
    sig = signature(category, "SyntaxError at line 5")
    for index in range(3):
        run = store.new_run(f"request {index}", "spark")
        store.record_failure(run, "core", sig, category, {"error": "syntax"})
    proposals = propose(store)
    assert len(proposals) == 1
    assert proposals[0]["mode"] == "proposal_only"
    assert propose(store) == []
    benchmark_id = store.record_benchmark({"chip": "M4"}, [{"passed": True}], "legacy")
    assert len(benchmark_id) == 32
    store.close()
