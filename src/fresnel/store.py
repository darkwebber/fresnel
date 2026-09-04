"""SQLite persistence for runs, events, metrics, and improvement evidence."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .config import state_path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  status TEXT NOT NULL, request TEXT NOT NULL, model TEXT NOT NULL,
  prompt_version TEXT NOT NULL, policy_version TEXT NOT NULL,
  result_json TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, created_at REAL NOT NULL,
  kind TEXT NOT NULL, payload_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(id)
);
CREATE TABLE IF NOT EXISTS model_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, component_id TEXT,
  prompt_tokens INTEGER NOT NULL DEFAULT 0, cached_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0, seconds REAL NOT NULL DEFAULT 0,
  success INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, component_id TEXT,
  signature TEXT NOT NULL, category TEXT NOT NULL, details_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS failures_signature_idx ON failures(signature, category);
CREATE TABLE IF NOT EXISTS improvements (
  id TEXT PRIMARY KEY, created_at REAL NOT NULL, signature TEXT NOT NULL,
  status TEXT NOT NULL, proposal_json TEXT NOT NULL, evaluation_json TEXT
);
CREATE TABLE IF NOT EXISTS benchmarks (
  id TEXT PRIMARY KEY, created_at REAL NOT NULL, hardware_json TEXT NOT NULL,
  results_json TEXT NOT NULL, selected_profile TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or state_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def new_run(
        self, request: str, model: str, prompt_version: str = "spark-v1", policy_version: str = "v1"
    ) -> str:
        run_id = uuid.uuid4().hex
        now = time.time()
        self.connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (run_id, now, now, "RECEIVED", request, model, prompt_version, policy_version),
        )
        self.connection.commit()
        return run_id

    def event(self, run_id: str, kind: str, payload: dict[str, Any]) -> None:
        now = time.time()
        self.connection.execute(
            "INSERT INTO events(run_id, created_at, kind, payload_json) VALUES (?, ?, ?, ?)",
            (run_id, now, kind, json.dumps(payload)),
        )
        self.connection.execute(
            "UPDATE runs SET status=?, updated_at=? WHERE id=?", (kind, now, run_id)
        )
        self.connection.commit()

    def finish(self, run_id: str, status: str, result: dict[str, Any]) -> None:
        self.connection.execute(
            "UPDATE runs SET status=?, updated_at=?, result_json=? WHERE id=?",
            (status, time.time(), json.dumps(result), run_id),
        )
        self.connection.commit()

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, created_at, status, request, model FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def repeated_failures(self, minimum: int = 3) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT signature, category, COUNT(*) AS count, COUNT(DISTINCT run_id) AS runs "
            "FROM failures GROUP BY signature, category HAVING count >= ? AND runs >= 2",
            (minimum,),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_call(
        self, run_id: str, component_id: str, usage: dict[str, Any], seconds: float, success: bool
    ) -> None:
        self.connection.execute(
            "INSERT INTO model_calls(run_id, component_id, prompt_tokens, cached_tokens, completion_tokens, seconds, success) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                component_id,
                usage.get("prompt_tokens", 0),
                usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
                usage.get("completion_tokens", 0),
                seconds,
                int(success),
            ),
        )
        self.connection.commit()

    def record_failure(
        self, run_id: str, component_id: str, signature: str, category: str, details: dict[str, Any]
    ) -> None:
        self.connection.execute(
            "INSERT INTO failures(run_id, component_id, signature, category, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, component_id, signature, category, json.dumps(details), time.time()),
        )
        self.connection.commit()

    def record_benchmark(
        self, hardware: dict[str, Any], results: Any, selected_profile: str
    ) -> str:
        benchmark_id = uuid.uuid4().hex
        self.connection.execute(
            "INSERT INTO benchmarks VALUES (?, ?, ?, ?, ?)",
            (
                benchmark_id,
                time.time(),
                json.dumps(hardware),
                json.dumps(results),
                selected_profile,
            ),
        )
        self.connection.commit()
        return benchmark_id

    def add_improvement(self, signature: str, proposal: dict[str, Any]) -> str:
        improvement_id = uuid.uuid4().hex
        self.connection.execute(
            "INSERT INTO improvements(id, created_at, signature, status, proposal_json) VALUES (?, ?, ?, ?, ?)",
            (improvement_id, time.time(), signature, "PROPOSED", json.dumps(proposal)),
        )
        self.connection.commit()
        return improvement_id

    def improvements(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, created_at, signature, status, proposal_json, evaluation_json FROM improvements ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
