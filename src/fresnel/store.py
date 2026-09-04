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
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, root TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
  updated_at REAL NOT NULL, git_head TEXT
);
CREATE TABLE IF NOT EXISTS task_charters (
  id TEXT PRIMARY KEY, project_id TEXT, run_id TEXT, revision INTEGER NOT NULL,
  goal TEXT NOT NULL, acceptance_json TEXT NOT NULL, constraints_json TEXT NOT NULL,
  scope_json TEXT NOT NULL, base_commit TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_state (
  run_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, run_id TEXT, session_id TEXT,
  created_at REAL NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memory_events_run_idx ON memory_events(run_id, id);
CREATE INDEX IF NOT EXISTS memory_events_session_idx ON memory_events(session_id, id);
CREATE TABLE IF NOT EXISTS memory_blobs (
  id TEXT PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0, expires_at REAL, path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_facts (
  id TEXT PRIMARY KEY, project_id TEXT, run_id TEXT, kind TEXT NOT NULL, value_json TEXT NOT NULL,
  source TEXT NOT NULL, source_hash TEXT, confidence REAL NOT NULL, valid INTEGER NOT NULL DEFAULT 1,
  supersedes TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS response_sessions (
  id TEXT PRIMARY KEY, project_id TEXT, name TEXT NOT NULL, system TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL, status TEXT NOT NULL,
  UNIQUE(project_id, name)
);
CREATE TABLE IF NOT EXISTS response_segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
  segment INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
  finish_reason TEXT, usage_json TEXT NOT NULL, created_at REAL NOT NULL,
  UNIQUE(turn_id, segment, role)
);
CREATE TABLE IF NOT EXISTS playbooks (
  id TEXT PRIMARY KEY, scope_json TEXT NOT NULL, trigger TEXT NOT NULL, rule TEXT NOT NULL,
  evidence_json TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS integration_installs (
  product TEXT NOT NULL, project_root TEXT NOT NULL, destination TEXT NOT NULL,
  version TEXT NOT NULL, checksum TEXT NOT NULL, updated_at REAL NOT NULL,
  PRIMARY KEY(product, project_root, destination)
);
CREATE TABLE IF NOT EXISTS repository_files (
  project_id TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
  language TEXT NOT NULL, indexed_at REAL NOT NULL,
  PRIMARY KEY(project_id, path)
);
CREATE TABLE IF NOT EXISTS repository_symbols (
  project_id TEXT NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, signature TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS repository_symbols_name_idx ON repository_symbols(project_id, name);
CREATE VIRTUAL TABLE IF NOT EXISTS repository_fts USING fts5(
  project_id UNINDEXED, path UNINDEXED, content
);
CREATE TABLE IF NOT EXISTS workspaces (
  run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, root TEXT NOT NULL,
  source_root TEXT NOT NULL, source_hashes_json TEXT NOT NULL, plan_json TEXT NOT NULL,
  state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL
);
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, component_id TEXT, sequence INTEGER NOT NULL,
  state_json TEXT NOT NULL, hashes_json TEXT NOT NULL, report_json TEXT NOT NULL,
  created_at REAL NOT NULL, UNIQUE(run_id, sequence)
);
CREATE TABLE IF NOT EXISTS idempotency_records (
  key TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, request_json TEXT NOT NULL,
  result_json TEXT, state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS capability_calls (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, component_id TEXT NOT NULL,
  capability TEXT NOT NULL, intent TEXT NOT NULL, request_json TEXT NOT NULL,
  result_json TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS context_manifests (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, component_id TEXT NOT NULL, attempt INTEGER NOT NULL,
  budget_tokens INTEGER NOT NULL, used_tokens INTEGER NOT NULL, items_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS context_feedback (
  manifest_id TEXT PRIMARY KEY, usefulness REAL NOT NULL, outcome TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS user_settings (
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_observations (
  id TEXT PRIMARY KEY, fact_key TEXT NOT NULL, project_id TEXT, run_id TEXT,
  value_json TEXT NOT NULL, source TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS fact_observations_key_idx ON fact_observations(fact_key, created_at);
CREATE TABLE IF NOT EXISTS run_control (
  run_id TEXT PRIMARY KEY, cancelled INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or state_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        previous_version = None
        has_meta = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if has_meta:
            row = self.connection.execute(
                "SELECT value FROM schema_meta WHERE key='memory_schema'"
            ).fetchone()
            previous_version = row["value"] if row else None
        if previous_version and previous_version != "2":
            backup_path = self.path.with_name(
                f"{self.path.name}.backup-v{previous_version}-{int(time.time())}"
            )
            backup = sqlite3.connect(backup_path)
            try:
                self.connection.backup(backup)
            finally:
                backup.close()
        self.connection.executescript(SCHEMA)
        self.connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('memory_schema', '2')"
        )
        self.connection.commit()

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

    def progress_event(self, run_id: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO events(run_id, created_at, kind, payload_json) VALUES (?, ?, 'PROGRESS', ?)",
            (run_id, time.time(), json.dumps(payload)),
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

    def run(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json")) if result["result_json"] else None
        return result

    def cancel(self, run_id: str) -> bool:
        run = self.run(run_id)
        if not run:
            return False
        if run["status"] in {
            "READY_TO_APPLY",
            "APPLIED",
            "COMPONENT_FAILED",
            "FAILED",
            "CANCELLED",
        }:
            return False
        now = time.time()
        self.connection.execute(
            "INSERT INTO run_control(run_id, cancelled, updated_at) VALUES (?, 1, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET cancelled=1, updated_at=excluded.updated_at",
            (run_id, now),
        )
        self.connection.execute(
            "UPDATE runs SET status='CANCEL_REQUESTED', updated_at=? WHERE id=?", (now, run_id)
        )
        self.connection.commit()
        return True

    def cancelled(self, run_id: str) -> bool:
        row = self.connection.execute(
            "SELECT cancelled FROM run_control WHERE run_id=?", (run_id,)
        ).fetchone()
        return bool(row and row["cancelled"])

    def clear_cancel(self, run_id: str) -> None:
        self.connection.execute(
            "UPDATE run_control SET cancelled=0, updated_at=? WHERE run_id=?",
            (time.time(), run_id),
        )
        self.connection.commit()

    def idempotency_result(self, key: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT state, result_json FROM idempotency_records WHERE key=?", (key,)
        ).fetchone()
        if not row or row["state"] != "COMPLETED":
            return None
        return json.loads(row["result_json"] or "{}")

    def idempotency_state(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT state FROM idempotency_records WHERE key=?", (key,)
        ).fetchone()
        return str(row["state"]) if row else None

    def idempotency_start(
        self, key: str, run_id: str, kind: str, request: dict[str, Any]
    ) -> None:
        now = time.time()
        self.connection.execute(
            "INSERT OR IGNORE INTO idempotency_records VALUES (?, ?, ?, ?, NULL, 'STARTED', ?, ?)",
            (key, run_id, kind, json.dumps(request, sort_keys=True), now, now),
        )
        self.connection.commit()

    def idempotency_finish(self, key: str, result: dict[str, Any]) -> None:
        self.connection.execute(
            "UPDATE idempotency_records SET state='COMPLETED', result_json=?, updated_at=? "
            "WHERE key=?",
            (json.dumps(result), time.time(), key),
        )
        self.connection.commit()

    def context_feedback(self, manifest_id: str, usefulness: float, outcome: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO context_feedback VALUES (?, ?, ?, ?)",
            (manifest_id, usefulness, outcome, time.time()),
        )
        self.connection.commit()

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

    def memory_event(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        project_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        cursor = self.connection.execute(
            "INSERT INTO memory_events(project_id, run_id, session_id, created_at, kind, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, run_id, session_id, time.time(), kind, json.dumps(payload)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def memory_events(
        self, *, run_id: str | None = None, session_id: str | None = None
    ) -> list[dict[str, Any]]:
        if run_id:
            rows = self.connection.execute(
                "SELECT * FROM memory_events WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
        elif session_id:
            rows = self.connection.execute(
                "SELECT * FROM memory_events WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM memory_events ORDER BY id DESC LIMIT 100"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result
