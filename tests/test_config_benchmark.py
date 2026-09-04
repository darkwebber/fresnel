import pytest

from fresnel import benchmark, config
from fresnel.config import Config, load_config, save_config
from fresnel.hardware import Hardware


def test_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    config = Config(profile="balanced", coordinator_input_cost_per_million=0.5)
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.coordinator_input_cost_per_million == 0.5
    assert loaded.selected_profile.max_output_tokens == 4096


def test_profiles_reserve_context():
    profiles = benchmark.select_profiles(32768, 8192)
    for values in profiles.values():
        assert (
            values["max_input_tokens"] + values["max_output_tokens"] + values["safety_tokens"]
            <= values["context_window"]
        )
    assert profiles["balanced"]["context_window"] == 24576


def test_keychain_is_explicitly_macos_only(monkeypatch):
    monkeypatch.setattr(config.platform, "system", lambda: "Linux")
    assert config.keychain_get("exa-api-key") is None
    with pytest.raises(RuntimeError, match="only available on macOS"):
        config.keychain_set("exa-api-key", "secret")


def test_calibrate_stops_on_pressure(monkeypatch):
    hardware = Hardware("arm64", "Apple M4 Pro", "15.0", 24 * 1024**3, 12, "ac", "nominal", 0)
    monkeypatch.setattr(benchmark, "detect", lambda: hardware)
    calls = []

    def fake_request(endpoint, prompt, output):
        calls.append((len(prompt), output))
        return {
            "ok": len(calls) < 2,
            "swap_delta_bytes": 0,
            "thermal_state": "nominal",
            "seconds": 1,
            "prompt_tokens": 1,
            "cached_tokens": 0,
            "completion_tokens": 1,
            "peak_memory_gb": None,
            "requested_output_tokens": output,
        }

    monkeypatch.setattr(benchmark, "request", fake_request)
    result = benchmark.calibrate("http://local", quick=True)
    assert result["selected_profile"] == "balanced"
    assert result["results"][0]["probe"] == "warmup"
    assert any(item["probe"] == "repeated_prompt_cache" for item in result["results"])
