from fresnel import hardware


def test_no_recorded_warning_is_nominal(monkeypatch):
    monkeypatch.setattr(
        hardware,
        "_command",
        lambda _argv: "Note: No thermal warning level has been recorded",
    )
    assert hardware.thermal_state() == "nominal"


def test_real_warning_is_serious(monkeypatch):
    monkeypatch.setattr(hardware, "_command", lambda _argv: "Thermal Warning: serious")
    assert hardware.thermal_state() == "serious"


def test_memory_pressure_parser(monkeypatch):
    monkeypatch.setattr(
        hardware, "_command", lambda _argv: "System-wide memory free percentage: 47%"
    )
    assert hardware.memory_free_percent() == 47
