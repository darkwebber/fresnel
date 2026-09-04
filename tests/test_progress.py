import io
import json
import time

from fresnel.progress import BenchmarkProgress


def test_progress_renders_probe_and_summary():
    stream = io.StringIO()
    progress = BenchmarkProgress(stream, enabled=True)
    progress({"state": "started", "label": "Testing context"})
    time.sleep(0.12)
    progress(
        {
            "state": "completed",
            "label": "Testing context",
            "seconds": 1.25,
            "memory_free_percent": 72,
            "cached_tokens": 64,
        }
    )
    progress(
        {
            "state": "finished",
            "label": "Calibration complete",
            "selected_profile": "balanced",
            "maximum_context": 24576,
            "maximum_output": 4096,
        }
    )
    output = stream.getvalue()
    assert "Testing context" in output
    assert "memory free 72%" in output
    assert "balanced profile" in output


def test_progress_is_silent_when_disabled():
    stream = io.StringIO()
    progress = BenchmarkProgress(stream, enabled=False)
    progress({"state": "started", "label": "Hidden"})
    progress({"state": "completed", "label": "Hidden", "seconds": 1})
    assert stream.getvalue() == ""


def test_progress_json_mode_is_machine_readable_and_includes_eta():
    stream = io.StringIO()
    progress = BenchmarkProgress(stream, mode="json")
    progress(
        {
            "state": "updated",
            "phase": "worker",
            "label": "Spark is working",
            "progress": 1,
            "total": 3,
            "eta_seconds": 12,
        }
    )
    line = stream.getvalue().removeprefix("FRESNEL_PROGRESS ")
    event = json.loads(line)
    assert event["phase"] == "worker"
    assert event["eta_seconds"] == 12
