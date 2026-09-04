"""Conservative failure classification and improvement proposals."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .store import Store

CATEGORIES = (
    ("protocol", ("invalid operation", "outside edit blocks", "no valid")),
    ("syntax", ("syntaxerror", "indentationerror")),
    ("wrong_scope", ("non-target", "path escapes", "contract")),
    ("api_hallucination", ("attributeerror", "modulenotfounderror", "has no attribute")),
    ("ineffective_repair", ("same patch", "matched 0", "matched exactly")),
    ("semantic", ("assertionerror", "failed")),
    ("integration", ("integration",)),
    ("truncation", ("finish_reason.*length", "truncated")),
)


def classify_failure(text: str) -> str:
    lowered = text.lower()
    for category, patterns in CATEGORIES:
        if any(re.search(pattern, lowered) for pattern in patterns):
            return category
    return "unknown"


def signature(category: str, text: str) -> str:
    normalized = re.sub(r"/[^\s:]+", "<path>", text.lower())
    normalized = re.sub(r"\b\d+\b", "<n>", normalized)
    normalized = re.sub(r"\s+", " ", normalized)[:1000]
    return hashlib.sha256(f"{category}:{normalized}".encode()).hexdigest()[:20]


def intervention(category: str) -> str:
    return {
        "protocol": "strengthen worker output grammar or deterministic parser",
        "syntax": "add compile validation before semantic tests",
        "wrong_scope": "strengthen target and contract enforcement",
        "api_hallucination": "add local-first reference request to the task profile",
        "ineffective_repair": "add repair-delta detection and stop repeated edits",
        "semantic": "add a regression contract and explicit algorithm invariant",
        "integration": "strengthen component interface contracts",
        "truncation": "reduce output scope or adjust calibrated output limit",
    }.get(category, "request orchestrator classification")


def propose(store: Store) -> list[dict[str, Any]]:
    proposals = []
    existing = {item["signature"] for item in store.improvements()}
    for failure in store.repeated_failures(minimum=3):
        if failure["signature"] in existing:
            continue
        proposal = {
            "signature": failure["signature"],
            "category": failure["category"],
            "observations": failure["count"],
            "distinct_runs": failure["runs"],
            "intervention": intervention(failure["category"]),
            "mode": "proposal_only",
            "promotion_gates": {
                "trigger_regressions_pass": True,
                "new_failures": 0,
                "max_output_token_increase_percent": 15,
                "max_latency_increase_percent": 15,
                "approval_risk_increase": False,
            },
        }
        proposal["id"] = store.add_improvement(failure["signature"], proposal)
        proposals.append(proposal)
    return proposals
