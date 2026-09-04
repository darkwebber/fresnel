"""Durable, repository-scoped memory with deterministic replay and expiring blobs."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import blobs_dir
from .store import Store

RAW_RETENTION_SECONDS = 30 * 24 * 60 * 60
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|token|password)(\s*[:=]\s*)([^\s,;]+)"
)


def redact(text: str) -> str:
    return SECRET_RE.sub(r"\1\2[REDACTED]", text)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def repository_root(path: Path | None = None) -> Path | None:
    candidate = (path or Path.cwd()).resolve()
    root = _git(candidate, "rev-parse", "--show-toplevel")
    return Path(root).resolve() if root else None


def project_id(path: Path | None = None) -> tuple[str | None, Path | None]:
    root = repository_root(path)
    if root is None:
        return None, None
    common = _git(root, "rev-parse", "--git-common-dir") or str(root / ".git")
    identity = f"{root}\0{Path(common).resolve() if Path(common).is_absolute() else common}"
    return hashlib.sha256(identity.encode()).hexdigest()[:24], root


@dataclass
class TaskState:
    phase: str = "planned"
    current_component: str | None = None
    done: list[str] = field(default_factory=list)
    doing: str = ""
    next: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    touched_files: list[str] = field(default_factory=list)
    last_validation: dict[str, Any] | None = None


def reduce_events(events: list[dict[str, Any]]) -> TaskState:
    """Build the current situation from facts; generated prose is never authoritative."""
    state = TaskState()
    for event in events:
        kind = event["kind"]
        payload = event.get("payload", {})
        if kind == "TASK_STARTED":
            state.phase = "implementation"
            state.next = list(payload.get("components", []))
            state.invariants = list(payload.get("invariants", []))
        elif kind == "COMPONENT_STARTED":
            state.current_component = payload.get("component_id")
            state.doing = payload.get("task", "")
            state.next = [item for item in state.next if item != state.current_component]
        elif kind == "EDIT_APPLIED":
            for path in payload.get("paths", []):
                if path not in state.touched_files:
                    state.touched_files.append(path)
        elif kind == "VALIDATION":
            state.last_validation = payload
            if not payload.get("passed", False):
                state.blockers = [payload.get("summary", "validation failed")]
        elif kind == "COMPONENT_COMPLETED":
            component = payload.get("component_id")
            if component and component not in state.done:
                state.done.append(component)
            state.blockers = []
            state.current_component = None
            state.doing = ""
        elif kind == "RUN_COMPLETED":
            state.phase = "complete"
            state.current_component = None
            state.doing = ""
            state.next = []
        elif kind in {"RUN_FAILED", "INTERRUPTED"}:
            state.phase = "blocked"
            state.blockers = [payload.get("summary", kind.lower())]
    return state


class Memory:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def ensure_project(self, path: Path) -> tuple[str, Path]:
        identifier, root = project_id(path)
        if not identifier or not root:
            root = path.resolve()
            if not root.is_dir():
                raise ValueError(f"project directory does not exist: {path}")
            identifier = hashlib.sha256(f"directory\0{root}".encode()).hexdigest()[:24]
        now = time.time()
        head = _git(root, "rev-parse", "HEAD")
        self.store.connection.execute(
            "INSERT INTO projects(id, root, created_at, updated_at, git_head) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET root=excluded.root, updated_at=excluded.updated_at, "
            "git_head=excluded.git_head",
            (identifier, str(root), now, now, head),
        )
        self.store.connection.commit()
        return identifier, root

    def _session_scope(self, repo: Path | None) -> str:
        return self.ensure_project(repo)[0] if repo is not None else "__global__"

    def create_charter(
        self,
        run_id: str,
        repo: Path,
        goal: str,
        acceptance: list[str],
        constraints: list[str],
        scope: list[str],
    ) -> str:
        identifier, root = self.ensure_project(repo)
        charter_id = uuid.uuid4().hex
        self.store.connection.execute(
            "INSERT INTO task_charters VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
            (
                charter_id,
                identifier,
                run_id,
                goal,
                json.dumps(acceptance),
                json.dumps(constraints),
                json.dumps(scope),
                _git(root, "rev-parse", "HEAD"),
                time.time(),
            ),
        )
        self.store.connection.commit()
        return charter_id

    def event(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        repo: Path | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> int:
        identifier = self.ensure_project(repo)[0] if repo else None
        event_id = self.store.memory_event(
            kind, payload, project_id=identifier, run_id=run_id, session_id=session_id
        )
        if run_id:
            state = reduce_events(self.store.memory_events(run_id=run_id))
            self.store.connection.execute(
                "INSERT INTO task_state(run_id, state_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET state_json=excluded.state_json, "
                "updated_at=excluded.updated_at",
                (run_id, json.dumps(asdict(state)), time.time()),
            )
            self.store.connection.commit()
        return event_id

    def put_blob(self, kind: str, content: str | bytes, *, pinned: bool = False) -> str:
        if isinstance(content, str):
            raw = redact(content).encode()
        else:
            try:
                raw = redact(content.decode()).encode()
            except UnicodeDecodeError:
                raw = content
        identifier = hashlib.sha256(raw).hexdigest()
        target = blobs_dir() / f"{identifier}.gz"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        if not target.exists():
            with gzip.open(target, "wb") as handle:
                handle.write(raw)
            target.chmod(0o600)
        now = time.time()
        expiry = None if pinned else now + RAW_RETENTION_SECONDS
        self.store.connection.execute(
            "INSERT INTO memory_blobs VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET pinned=MAX(pinned, excluded.pinned), "
            "expires_at=CASE WHEN MAX(pinned, excluded.pinned)=1 THEN NULL ELSE excluded.expires_at END",
            (identifier, now, kind, len(raw), int(pinned), expiry, str(target)),
        )
        self.store.connection.commit()
        return identifier

    def get_blob(self, identifier: str) -> bytes:
        row = self.store.connection.execute(
            "SELECT path FROM memory_blobs WHERE id=?", (identifier,)
        ).fetchone()
        if not row:
            raise KeyError(identifier)
        with gzip.open(row["path"], "rb") as handle:
            return handle.read()

    def pin(self, identifier: str) -> None:
        cursor = self.store.connection.execute(
            "UPDATE memory_blobs SET pinned=1, expires_at=NULL WHERE id=?", (identifier,)
        )
        self.store.connection.commit()
        if cursor.rowcount != 1:
            raise KeyError(identifier)

    def gc(self, *, dry_run: bool = False, now: float | None = None) -> list[str]:
        rows = self.store.connection.execute(
            "SELECT id, path FROM memory_blobs WHERE pinned=0 AND expires_at IS NOT NULL "
            "AND expires_at < ?",
            (now or time.time(),),
        ).fetchall()
        active_runs = {
            row["run_id"]
            for row in self.store.connection.execute(
                "SELECT run_id, state_json FROM task_state"
            ).fetchall()
            if json.loads(row["state_json"]).get("phase") not in {"complete", "failed"}
        }
        protected_text = "\n".join(
            row["payload_json"]
            for row in self.store.connection.execute(
                "SELECT run_id, payload_json FROM memory_events"
            ).fetchall()
            if row["run_id"] in active_runs
        )
        protected_text += "\n" + "\n".join(
            row["evidence_json"]
            for row in self.store.connection.execute(
                "SELECT evidence_json FROM playbooks WHERE status='PROMOTED'"
            ).fetchall()
        )
        rows = [row for row in rows if row["id"] not in protected_text]
        removed = [row["id"] for row in rows]
        if not dry_run:
            for row in rows:
                Path(row["path"]).unlink(missing_ok=True)
            self.store.connection.executemany(
                "DELETE FROM memory_blobs WHERE id=?", [(item,) for item in removed]
            )
            self.store.connection.commit()
        return removed

    def status(self, repo: Path | None = None) -> dict[str, Any]:
        if repo is not None:
            identifier, root = self.ensure_project(repo)
        else:
            identifier, root = None, None
        where = " WHERE project_id=?" if identifier else ""
        params = (identifier,) if identifier else ()
        events = self.store.connection.execute(
            f"SELECT COUNT(*) AS count FROM memory_events{where}", params
        ).fetchone()["count"]
        sessions = self.store.connection.execute(
            f"SELECT COUNT(*) AS count FROM response_sessions{where}", params
        ).fetchone()["count"]
        blobs = self.store.connection.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS bytes FROM memory_blobs"
        ).fetchone()
        return {
            "project_id": identifier,
            "project_root": str(root) if root else None,
            "events": events,
            "sessions": sessions,
            "blobs": blobs["count"],
            "blob_bytes": blobs["bytes"],
            "retention_days": 30,
        }

    def inspect(self, *, run_id: str | None = None, session_id: str | None = None) -> dict:
        state = None
        stored_state = None
        events = self.store.memory_events(run_id=run_id, session_id=session_id)
        charter = None
        if run_id:
            row = self.store.connection.execute(
                "SELECT state_json FROM task_state WHERE run_id=?", (run_id,)
            ).fetchone()
            stored_state = json.loads(row["state_json"]) if row else None
            state = asdict(reduce_events(events))
            charter_row = self.store.connection.execute(
                "SELECT * FROM task_charters WHERE run_id=? ORDER BY revision DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if charter_row:
                charter = dict(charter_row)
                for key in ("acceptance_json", "constraints_json", "scope_json"):
                    charter[key.removesuffix("_json")] = json.loads(charter.pop(key))
        messages = self.session_messages(session_id) if session_id else None
        return {
            "run_id": run_id,
            "session_id": session_id,
            "charter": charter,
            "state": state,
            "stored_state_consistent": stored_state is None or stored_state == state,
            "events": events,
            "messages": messages,
        }

    def get_or_create_session(
        self, name: str, *, repo: Path | None = None, system: str = ""
    ) -> dict[str, Any]:
        if not name or any(char in name for char in "\r\n\0"):
            raise ValueError("session name must be non-empty and single-line")
        scope = self._session_scope(repo)
        row = self.store.connection.execute(
            "SELECT * FROM response_sessions WHERE project_id=? AND name=?", (scope, name)
        ).fetchone()
        if row:
            return dict(row)
        now = time.time()
        session_id = uuid.uuid4().hex
        self.store.connection.execute(
            "INSERT INTO response_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, scope, name, system, now, now, "ACTIVE"),
        )
        self.store.connection.commit()
        return dict(
            self.store.connection.execute(
                "SELECT * FROM response_sessions WHERE id=?", (session_id,)
            ).fetchone()
        )

    def session_by_name(self, name: str, *, repo: Path | None = None) -> dict[str, Any] | None:
        scope = self._session_scope(repo)
        row = self.store.connection.execute(
            "SELECT * FROM response_sessions WHERE project_id=? AND name=?", (scope, name)
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, *, repo: Path | None = None) -> list[dict[str, Any]]:
        scope = self._session_scope(repo)
        rows = self.store.connection.execute(
            "SELECT id, name, status, created_at, updated_at FROM response_sessions "
            "WHERE project_id=? ORDER BY updated_at DESC",
            (scope,),
        ).fetchall()
        return [dict(row) for row in rows]

    def session_messages(self, session_id: str, *, character_limit: int = 24000) -> list[dict[str, str]]:
        rows = self.store.connection.execute(
            "SELECT turn_id, role, GROUP_CONCAT(content, '') AS content, MIN(id) AS first_id "
            "FROM response_segments WHERE session_id=? GROUP BY turn_id, role "
            "ORDER BY first_id",
            (session_id,),
        ).fetchall()
        messages = [{"role": row["role"], "content": row["content"]} for row in rows]
        total = sum(len(item["content"]) for item in messages)
        if total <= character_limit:
            return messages
        recent: list[dict[str, str]] = []
        used = 0
        for item in reversed(messages):
            if recent and used + len(item["content"]) > int(character_limit * 0.7):
                break
            recent.append(item)
            used += len(item["content"])
        older = messages[: len(messages) - len(recent)]
        digest = "\n".join(
            f"- {item['role']}: {item['content'][:240].replace(chr(10), ' ')}" for item in older
        )
        summary = {
            "role": "system",
            "content": "Older session index (retrieve from Fresnel memory if needed):\n" + digest,
        }
        return [summary, *reversed(recent)]

    def interrupted_turn(self, session_id: str) -> dict[str, Any]:
        """Return the exact persisted tail needed to resume an interrupted response."""
        row = self.store.connection.execute(
            "SELECT turn_id, MAX(segment) AS last_segment FROM response_segments "
            "WHERE session_id=? AND role='assistant' GROUP BY turn_id ORDER BY MAX(id) DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            raise ValueError("session has no interrupted assistant response")
        parts = self.store.connection.execute(
            "SELECT content FROM response_segments WHERE session_id=? AND turn_id=? "
            "AND role='assistant' ORDER BY segment",
            (session_id, row["turn_id"]),
        ).fetchall()
        return {
            "turn_id": row["turn_id"],
            "next_segment": int(row["last_segment"]) + 1,
            "content": "".join(part["content"] for part in parts),
        }

    def add_response_segment(
        self,
        session_id: str,
        turn_id: str,
        segment: int,
        role: str,
        content: str,
        finish_reason: str | None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self.store.connection.execute(
            "INSERT OR REPLACE INTO response_segments(session_id, turn_id, segment, role, "
            "content, finish_reason, usage_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                turn_id,
                segment,
                role,
                redact(content),
                finish_reason,
                json.dumps(usage or {}),
                time.time(),
            ),
        )
        status = "COMPLETE" if finish_reason == "stop" else "INTERRUPTED"
        self.store.connection.execute(
            "UPDATE response_sessions SET updated_at=?, status=? WHERE id=?",
            (time.time(), status, session_id),
        )
        self.store.connection.commit()

    def forget(
        self, *, run_id: str | None = None, session_id: str | None = None, repo: Path | None = None
    ) -> int:
        if sum(value is not None for value in (run_id, session_id, repo)) != 1:
            raise ValueError("select exactly one run, session, or project")
        connection = self.store.connection
        if run_id:
            count = connection.execute(
                "DELETE FROM memory_events WHERE run_id=?", (run_id,)
            ).rowcount
            connection.execute("DELETE FROM task_state WHERE run_id=?", (run_id,))
            connection.execute("DELETE FROM task_charters WHERE run_id=?", (run_id,))
        elif session_id:
            count = connection.execute(
                "DELETE FROM memory_events WHERE session_id=?", (session_id,)
            ).rowcount
            connection.execute("DELETE FROM response_segments WHERE session_id=?", (session_id,))
            connection.execute("DELETE FROM response_sessions WHERE id=?", (session_id,))
        else:
            identifier, _root = self.ensure_project(repo or Path.cwd())
            count = connection.execute(
                "DELETE FROM memory_events WHERE project_id=?", (identifier,)
            ).rowcount
            sessions = connection.execute(
                "SELECT id FROM response_sessions WHERE project_id=?", (identifier,)
            ).fetchall()
            connection.executemany(
                "DELETE FROM response_segments WHERE session_id=?",
                [(row["id"],) for row in sessions],
            )
            connection.execute("DELETE FROM response_sessions WHERE project_id=?", (identifier,))
            connection.execute("DELETE FROM task_charters WHERE project_id=?", (identifier,))
            connection.execute("DELETE FROM projects WHERE id=?", (identifier,))
        connection.commit()
        return int(count)

    def close(self) -> None:
        self.store.close()


def remove_tree(path: Path) -> None:
    """Test/support helper kept explicit to avoid broad destructive targets."""
    if path.name != "memory":
        raise ValueError("refusing to remove a non-memory directory")
    shutil.rmtree(path)
