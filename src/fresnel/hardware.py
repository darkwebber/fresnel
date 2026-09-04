"""Non-privileged Apple Silicon hardware and pressure telemetry."""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import asdict, dataclass


def _command(argv: list[str]) -> str:
    completed = subprocess.run(
        argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
    )
    return completed.stdout.strip()


@dataclass(frozen=True)
class Hardware:
    architecture: str
    chip: str
    macos: str
    memory_bytes: int
    cpu_count: int
    power_source: str
    thermal_state: str
    swap_used_bytes: int

    def json(self) -> dict:
        return asdict(self)


def swap_used() -> int:
    text = _command(["sysctl", "-n", "vm.swapusage"])
    match = re.search(r"used = ([0-9.]+)([MG])", text)
    if not match:
        return 0
    multiplier = 1024**2 if match.group(2) == "M" else 1024**3
    return int(float(match.group(1)) * multiplier)


def memory_free_percent() -> int | None:
    text = _command(["memory_pressure", "-Q"])
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", text)
    return int(match.group(1)) if match else None


def thermal_state() -> str:
    text = _command(["pmset", "-g", "therm"]).lower()
    if "no thermal warning level has been recorded" in text:
        return "nominal"
    if "critical" in text:
        return "critical"
    if "serious" in text or "warning" in text:
        return "serious"
    if "fair" in text:
        return "fair"
    return "nominal"


def detect() -> Hardware:
    memory = _command(["sysctl", "-n", "hw.memsize"])
    chip = _command(["sysctl", "-n", "machdep.cpu.brand_string"])
    power = _command(["pmset", "-g", "batt"])
    return Hardware(
        architecture=platform.machine(),
        chip=chip or "unknown Apple Silicon",
        macos=platform.mac_ver()[0],
        memory_bytes=int(memory or 0),
        cpu_count=int(_command(["sysctl", "-n", "hw.logicalcpu"]) or 0),
        power_source="battery" if "Battery Power" in power else "ac",
        thermal_state=thermal_state(),
        swap_used_bytes=swap_used(),
    )


def validate_supported(hardware: Hardware) -> list[str]:
    problems = []
    if hardware.architecture != "arm64":
        problems.append("Fresnel currently requires an Apple Silicon arm64 Mac")
    major = int(hardware.macos.split(".", 1)[0]) if hardware.macos else 0
    if major < 14:
        problems.append("Fresnel requires macOS 14 or newer")
    if hardware.memory_bytes < 16 * 1024**3:
        problems.append("Spark 2.5 4B 8-bit requires at least 16 GB unified memory")
    return problems
