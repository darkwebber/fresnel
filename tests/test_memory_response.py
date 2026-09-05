import json
from dataclasses import replace
from urllib.error import URLError

import pytest

from fresnel.config import Profile
from fresnel.memory import Memory, reduce_events
from fresnel.response import COMPLETE_MARKER, generate_response, markdown_incomplete, stitch
from fresnel.store import Store


def _reply(content, reason="stop", tokens=4):
    return {
        "content": content,
        "finish_reason": reason,
        "usage": {"prompt_tokens": 5, "completion_tokens": tokens},
        "seconds": 0.01,
    }


def _generate(question, replies, **kwargs):
    iterator = iter(replies)

    def complete_fn(*_args, **_kwargs):
        return next(iterator)

    max_continuations = kwargs.pop("max_continuations", 2)
    max_total_tokens = kwargs.pop("max_total_tokens", 96)
    return generate_response(
        "http://local",
        question,
        profile=replace(Profile(), max_output_tokens=64, max_input_tokens=1024),
        requested_tokens=32,
        max_continuations=max_continuations,
        max_total_tokens=max_total_tokens,
        temperature=0.15,
        top_p=0.9,
        top_k=40,
        min_p=0,
        system="system",
        streaming=False,
        complete_fn=complete_fn,
        **kwargs,
    )


def test_continuation_stitches_overlap_and_removes_control_marker():
    result = _generate(
        "write code",
        [
            _reply("alpha beta", "length", 32),
            _reply("beta gamma" + COMPLETE_MARKER, "stop", 4),
        ],
    )
    assert result["content"] == "alpha beta gamma"
    assert result["continuations"] == 1
    assert result["complete"] is True
    assert stitch("abcdefgh", "abcdefghij") == "abcdefghij"
    assert markdown_incomplete("```python\npass") is True


def test_named_session_resumes_the_same_interrupted_turn(tmp_path):
    memory = Memory(Store(tmp_path / "state.sqlite3"))
    first = _generate(
        "write file",
        [_reply("first half ", "length", 32)],
        max_continuations=0,
        memory=memory,
        session_name="build",
        repo=tmp_path,
    )
    assert first["complete"] is False

    captured = {}

    def complete_fn(*_args, **kwargs):
        captured["messages"] = kwargs["messages"]
        return _reply("second half" + COMPLETE_MARKER)

    resumed = generate_response(
        "http://local",
        "",
        profile=Profile(max_output_tokens=64, max_input_tokens=1024),
        requested_tokens=32,
        max_continuations=1,
        max_total_tokens=64,
        temperature=0.15,
        top_p=0.9,
        top_k=40,
        min_p=0,
        system="system",
        streaming=False,
        memory=memory,
        session_name="build",
        repo=tmp_path,
        resume=True,
        complete_fn=complete_fn,
    )
    assert resumed["content"] == "first half second half"
    assert captured["messages"][-2]["content"] == "first half "
    rows = memory.store.connection.execute(
        "SELECT DISTINCT turn_id FROM response_segments WHERE role='assistant'"
    ).fetchall()
    assert len(rows) == 1
    assert memory.session_by_name("build", repo=tmp_path)["status"] == "COMPLETE"
    memory.close()


def test_memory_replay_redaction_gc_and_project_forget(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3")
    memory = Memory(store)
    monkeypatch.setattr("fresnel.memory.blobs_dir", lambda: tmp_path / "memory" / "blobs")
    run_id = "run-1"
    memory.create_charter(run_id, tmp_path, "goal", ["passes"], ["safe"], ["a.py"])
    memory.event(
        "TASK_STARTED",
        {"components": ["one"], "invariants": ["safe"]},
        repo=tmp_path,
        run_id=run_id,
    )
    memory.event("COMPONENT_STARTED", {"component_id": "one", "task": "edit"}, run_id=run_id)
    memory.event("EDIT_APPLIED", {"paths": ["a.py"]}, run_id=run_id)
    state = memory.inspect(run_id=run_id)["state"]
    assert state["doing"] == "edit"
    assert state["touched_files"] == ["a.py"]

    blob = memory.put_blob("log", "token=secret", pinned=False)
    assert memory.get_blob(blob) == b"token=[REDACTED]"
    assert memory.gc(now=10**12, dry_run=True) == [blob]

    session = memory.get_or_create_session("chat", repo=tmp_path)
    memory.add_response_segment(session["id"], "turn", 0, "user", "hello", None)
    memory.forget(repo=tmp_path)
    assert not store.connection.execute("SELECT * FROM response_segments").fetchall()
    memory.close()


def test_reduce_events_is_deterministic():
    events = [
        {"kind": "TASK_STARTED", "payload": {"components": ["a"], "invariants": ["x"]}},
        {"kind": "COMPONENT_STARTED", "payload": {"component_id": "a", "task": "work"}},
        {"kind": "COMPONENT_COMPLETED", "payload": {"component_id": "a"}},
        {"kind": "RUN_COMPLETED", "payload": {}},
    ]
    assert json.loads(json.dumps(reduce_events(events).__dict__))["phase"] == "complete"


def test_resume_requires_an_interrupted_named_session(tmp_path):
    memory = Memory(Store(tmp_path / "state.sqlite3"))
    with pytest.raises(ValueError, match="no interrupted"):
        _generate(
            "",
            [_reply("unused")],
            memory=memory,
            session_name="missing",
            repo=tmp_path,
            resume=True,
        )
    memory.close()


def test_transient_stream_failure_continues_received_bytes(monkeypatch):
    calls = 0
    resets = []

    def stream_fn(_endpoint, _question, on_text, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            on_text("first ")
            raise URLError("temporary")
        assert _kwargs["messages"][-2]["content"] == "first "
        on_text("second")
        return _reply("second" + COMPLETE_MARKER)

    monkeypatch.setattr("fresnel.response.time.sleep", lambda _seconds: None)
    result = generate_response(
        "http://local",
        "question",
        profile=Profile(max_output_tokens=64, max_input_tokens=1024),
        requested_tokens=32,
        max_continuations=1,
        max_total_tokens=64,
        temperature=0.15,
        top_p=0.9,
        top_k=40,
        min_p=0,
        system="system",
        streaming=True,
        on_segment_reset=resets.append,
        stream_fn=stream_fn,
    )
    assert calls == 2
    assert resets == []
    assert result["content"] == "first second"


def test_stream_segments_are_durable_before_transport_finishes(tmp_path):
    memory = Memory(Store(tmp_path / "state.sqlite3"))

    def interrupted(_endpoint, _question, on_text, **_kwargs):
        on_text("durable partial")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        generate_response(
            "http://local",
            "question",
            profile=Profile(max_output_tokens=64, max_input_tokens=1024),
            requested_tokens=32,
            max_continuations=0,
            max_total_tokens=32,
            temperature=0.15,
            top_p=0.9,
            top_k=40,
            min_p=0,
            system="system",
            streaming=True,
            memory=memory,
            session_name="crash-safe",
            repo=tmp_path,
            stream_fn=interrupted,
        )
    session = memory.session_by_name("crash-safe", repo=tmp_path)
    partial = memory.interrupted_turn(session["id"])
    assert partial["content"] == "durable partial"
    assert session["status"] == "INTERRUPTED"
    memory.close()


def test_no_progress_on_broken_markdown_requests_suffix_not_replacement():
    conversations = []
    replies = iter(
        [
            _reply("```python\npass", "length", 32),
            _reply("\n" + COMPLETE_MARKER, "stop", 3),
            _reply("```" + COMPLETE_MARKER, "stop", 8),
        ]
    )

    def complete_fn(*_args, **kwargs):
        conversations.append(kwargs["messages"])
        return next(replies)

    result = generate_response(
        "http://local",
        "write code",
        profile=Profile(max_output_tokens=64, max_input_tokens=1024),
        requested_tokens=32,
        max_continuations=2,
        max_total_tokens=96,
        temperature=0.15,
        top_p=0.9,
        top_k=40,
        min_p=0,
        system="system",
        streaming=False,
        complete_fn=complete_fn,
    )
    assert result["content"] == "```python\npass\n```"
    assert "Continue exactly" in conversations[-1][-1]["content"]


def test_model_restarting_from_the_beginning_replaces_instead_of_duplicates():
    restarted = "A sufficiently long beginning of an answer, now complete."
    result = _generate(
        "answer",
        [
            _reply("A sufficiently long beginning of an answer", "length", 32),
            _reply(restarted + COMPLETE_MARKER, "stop", 12),
        ],
    )
    assert result["content"] == restarted


def test_stream_repeated_prefix_is_not_replayed_to_display():
    prefix = "A sufficiently long beginning of an answer"
    replies = iter([_reply(prefix, "length", 32), _reply(prefix + " finished" + COMPLETE_MARKER)])
    visible = []
    resets = []

    def stream_fn(_endpoint, _question, on_text, **_kwargs):
        reply = next(replies)
        for char in reply["content"]:
            on_text(char)
        return reply

    result = generate_response(
        "http://local",
        "answer",
        profile=Profile(),
        requested_tokens=32,
        max_continuations=1,
        max_total_tokens=64,
        temperature=0.15,
        top_p=0.9,
        top_k=40,
        min_p=0,
        system="system",
        streaming=True,
        stream_fn=stream_fn,
        on_text=visible.append,
        on_segment_reset=resets.append,
    )
    assert "".join(visible) == prefix + " finished"
    assert result["complete"]
    assert resets == []


def test_conflicting_restart_does_not_destroy_accepted_draft():
    prefix = "A sufficiently long beginning of an answer: "
    result = _generate(
        "answer",
        [
            _reply(prefix + "original", "length", 32),
            _reply(prefix + "changed" + COMPLETE_MARKER),
        ],
        max_continuations=1,
    )
    assert result["content"] == prefix + "original"
    assert not result["complete"]


def test_continuation_total_budget_is_enforced():
    result = _generate("answer", [_reply("partial", "length", 32)], max_total_tokens=32)
    assert not result["complete"]
    assert result["finish_reason"] == "total_limit"
    assert len(result["calls"]) == 1


def test_language_tag_is_not_a_closing_fence():
    assert markdown_incomplete("```python\npass\n```python\npass")
    assert not markdown_incomplete("~~~python\npass\n~~~")
    assert not markdown_incomplete("````python\n```\n````")
