import io
import json

from fresnel import chat, cli, sampling
from fresnel.cli import parser


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return io.BytesIO(json.dumps(self.body).encode())

    def __exit__(self, *_args):
        return False


def test_direct_chat_uses_requested_sampling(monkeypatch):
    captured = {}
    body = {
        "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }

    def fake_open(request, **_kwargs):
        captured.update(json.loads(request.data))
        return Response(body)

    monkeypatch.setattr(chat.urllib.request, "urlopen", fake_open)
    result = chat.complete(
        "http://local",
        "question",
        max_tokens=100,
        temperature=0.3,
        top_p=0.8,
        top_k=20,
        min_p=0.05,
    )
    assert result["content"] == "answer"
    assert captured["temperature"] == 0.3
    assert captured["top_p"] == 0.8


def test_streaming_chat_emits_sse_deltas(monkeypatch):
    captured = {}
    stream = b"".join(
        [
            b'data: {"choices":[{"delta":{"content":"hello "},"finish_reason":null}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"world"},"finish_reason":"stop"}]}\n\n',
            b'data: {"choices":[],"usage":{"completion_tokens":2}}\n\n',
            b"data: [DONE]\n\n",
        ]
    )

    class StreamResponse(Response):
        def __enter__(self):
            return io.BytesIO(stream)

    monkeypatch.setattr(
        chat.urllib.request,
        "urlopen",
        lambda request, **_kwargs: (
            captured.update(json.loads(request.data)) or StreamResponse(None)
        ),
    )
    chunks = []
    result = chat.stream_complete(
        "http://local",
        "question",
        chunks.append,
        max_tokens=100,
        temperature=0.15,
        top_p=0.9,
        top_k=40,
        min_p=0,
    )
    assert captured["stream"] is True
    assert captured["stream_options"] == {"include_usage": True}
    assert chunks == ["hello ", "world"]
    assert result["content"] == "hello world"
    assert result["usage"]["completion_tokens"] == 2
    assert result["finish_reason"] == "stop"


def test_behavior_tuner_prefers_balanced_temperature_on_tie():
    def fake_request(_endpoint, prompt, **_kwargs):
        if "FRESNEL_OK" in prompt:
            content = "FRESNEL_OK"
        elif "6 workers" in prompt:
            content = '{"answer": 42}'
        else:
            content = "def clamp(value, low, high):\n    return min(max(value, low), high)"
        return {"content": content, "finish_reason": "stop", "usage": {}, "seconds": 0.1}

    result = sampling.tune(
        "http://local", candidates=(0.0, 0.15, 0.3), request_fn=fake_request
    )
    assert result["selected_temperature"] == 0.15
    assert all(item["score"] == 3 for item in result["results"])


def test_cli_exposes_ask_tune_and_sampling_controls():
    ask = parser().parse_args(["ask", "hello", "--temperature", "0.2"])
    assert ask.temperature == 0.2
    assert ask.no_stream is False
    assert ask.max_continuations == 2
    tune = parser().parse_args(["tune", "--candidate", "0.1", "--candidate", "0.3"])
    assert tune.candidate == [0.1, 0.3]
    config = parser().parse_args(["config", "sampling", "--top-p", "0.8"])
    assert config.top_p == 0.8


def test_ask_automatically_continues_a_length_limited_stream(monkeypatch, capsys):
    replies = iter(
        [
            {"content": "first ", "finish_reason": "length", "usage": {}, "seconds": 0.1},
            {"content": "second", "finish_reason": "stop", "usage": {}, "seconds": 0.1},
        ]
    )
    conversations = []

    def fake_stream(_endpoint, _question, on_text, **kwargs):
        conversations.append(kwargs["messages"][:])
        result = next(replies)
        on_text(result["content"])
        return result

    monkeypatch.setattr(cli, "stream_complete", fake_stream)
    monkeypatch.setattr(cli, "memory_free_percent", lambda: 50)
    args = parser().parse_args(["ask", "write", "a", "file", "--max-tokens", "8"])
    assert args.handler(args) == 0
    assert capsys.readouterr().out == "first second\n"
    assert len(conversations) == 2
    assert conversations[1][-2] == {"role": "assistant", "content": "first "}
