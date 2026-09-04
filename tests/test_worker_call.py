import io
import json

import pytest

from fresnel import worker


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return io.BytesIO(json.dumps(self.body).encode())

    def __exit__(self, *_args):
        return False


def test_worker_call_detects_truncation(monkeypatch):
    body = {
        "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
        "usage": {"completion_tokens": 10},
    }
    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(body))
    with pytest.raises(ValueError, match="truncated"):
        worker.call("http://local", "spark", "prompt", 10)


def test_worker_call_sends_profile_sampling(monkeypatch):
    captured = {}
    body = {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]}

    def fake_open(request, **_kwargs):
        captured.update(json.loads(request.data))
        return Response(body)

    monkeypatch.setattr(worker.urllib.request, "urlopen", fake_open)
    worker.call(
        "http://local",
        "spark",
        "prompt",
        10,
        temperature=0.25,
        top_p=0.85,
        top_k=32,
        min_p=0.05,
    )
    assert captured["temperature"] == 0.25
    assert captured["top_p"] == 0.85
    assert captured["top_k"] == 32
    assert captured["min_p"] == 0.05
