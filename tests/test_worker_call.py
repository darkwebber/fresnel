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
