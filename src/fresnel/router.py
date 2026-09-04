"""Model registry and shadow routing decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelProfile:
    id: str
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    max_context: int
    preferred_output: int
    preferred_files: int


SPARK = ModelProfile(
    id="spark-2.5-4b-mlx-8bit",
    strengths=("bounded_python_edits", "simple_file_creation", "mechanical_repairs"),
    weaknesses=("architecture", "multi_component_ui", "subtle_dataframe_semantics"),
    max_context=32768,
    preferred_output=2048,
    preferred_files=2,
)


def shadow_route(task: dict, registry: tuple[ModelProfile, ...] = (SPARK,)) -> dict:
    selected = registry[0]
    reasons = ["Spark is the only production worker; alternative routing is shadow-only"]
    if len(task.get("targets", [])) > selected.preferred_files:
        reasons.append("task exceeds Spark's preferred file count; coordinator should decompose it")
    if task.get("api_uncertainty"):
        reasons.append("resolve references before worker execution")
    return {
        "mode": "shadow",
        "actual_worker": SPARK.id,
        "hypothetical_worker": selected.id,
        "reasons": reasons,
        "profile": asdict(selected),
    }
