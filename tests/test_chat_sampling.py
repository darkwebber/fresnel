import io
import json

from fresnel import chat, sampling
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
    tune = parser().parse_args(["tune", "--candidate", "0.1", "--candidate", "0.3"])
    assert tune.candidate == [0.1, 0.3]
    config = parser().parse_args(["config", "sampling", "--top-p", "0.8"])
    assert config.top_p == 0.8
