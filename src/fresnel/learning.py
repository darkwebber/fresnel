"""Conservative failure classification and improvement proposals."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
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


def evaluate(store: Store, improvement_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Promote only reversible instruction/retrieval rules that pass every safety gate."""
    row = store.connection.execute(
        "SELECT * FROM improvements WHERE id=?", (improvement_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"unknown improvement: {improvement_id}")
    kind = evidence.get("kind", "playbook")
    safe_kind = kind in {"prompt", "retrieval", "playbook"}
    passed = all(
        (
            evidence.get("trigger_regressions_pass") is True,
            int(evidence.get("new_failures", 1)) == 0,
            float(evidence.get("output_token_increase_percent", 100)) <= 15,
            float(evidence.get("latency_increase_percent", 100)) <= 15,
            evidence.get("approval_risk_increase") is False,
            safe_kind,
            bool(str(evidence.get("rule", "")).strip()),
        )
    )
    status = "PROMOTED" if passed else "REJECTED"
    playbook_id = None
    with store.connection:
        store.connection.execute(
            "UPDATE improvements SET status=?, evaluation_json=? WHERE id=?",
            (status, json.dumps(evidence, sort_keys=True), improvement_id),
        )
        if passed:
            proposal = json.loads(row["proposal_json"])
            trigger = proposal["signature"]
            now = time.time()
            store.connection.execute(
                "UPDATE playbooks SET status='SUPERSEDED', updated_at=? "
                "WHERE trigger=? AND status='ACTIVE'",
                (now, trigger),
            )
            playbook_id = uuid.uuid4().hex
            store.connection.execute(
                "INSERT INTO playbooks VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)",
                (
                    playbook_id,
                    json.dumps(evidence.get("scope", {"model": "spark-2.5-4b-mlx-8bit"})),
                    trigger,
                    str(evidence["rule"]).strip(),
                    json.dumps(evidence, sort_keys=True),
                    now,
                    now,
                ),
            )
    return {
        "improvement_id": improvement_id,
        "status": status,
        "playbook_id": playbook_id,
        "reversible": passed,
    }


def rollback(store: Store, playbook_id: str) -> dict[str, Any]:
    row = store.connection.execute(
        "SELECT trigger FROM playbooks WHERE id=? AND status='ACTIVE'", (playbook_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"active playbook not found: {playbook_id}")
    now = time.time()
    with store.connection:
        store.connection.execute(
            "UPDATE playbooks SET status='ROLLED_BACK', updated_at=? WHERE id=?",
            (now, playbook_id),
        )
        previous = store.connection.execute(
            "SELECT id FROM playbooks WHERE trigger=? AND status='SUPERSEDED' "
            "ORDER BY updated_at DESC LIMIT 1",
            (row["trigger"],),
        ).fetchone()
        if previous:
            store.connection.execute(
                "UPDATE playbooks SET status='ACTIVE', updated_at=? WHERE id=?",
                (now, previous["id"]),
            )
    return {"rolled_back": playbook_id, "restored": previous["id"] if previous else None}
