"""Durable, hash-verified workspaces and idempotent checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import state_path, workspaces_dir
from .protocol import Plan, safe_path
from .store import Store

RETENTION_SECONDS = 30 * 24 * 60 * 60
IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def source_hashes(repo: Path, paths: tuple[str, ...]) -> dict[str, str | None]:
    return {relative: digest(safe_path(repo, relative)) for relative in paths}


def workspace_base(store: Store) -> Path:
    return (
        workspaces_dir()
        if store.path.resolve() == state_path().resolve()
        else store.path.parent / "workspaces"
    )


class Workspace:
    def __init__(self, store: Store, run_id: str):
        self.store = store
        self.run_id = run_id

    @property
    def root(self) -> Path:
        row = self.store.connection.execute(
            "SELECT root FROM workspaces WHERE run_id=?", (self.run_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"workspace not found for run {self.run_id}")
        return Path(row["root"])

    @property
    def repo(self) -> Path:
        return self.root / "repo"

    @classmethod
    def create(
        cls,
        store: Store,
        run_id: str,
        project_id: str,
        source: Path,
        plan: Plan,
        tracked_paths: tuple[str, ...],
    ) -> Workspace:
        source = source.resolve()
        base = workspace_base(store)
        root = base / run_id
        if root.exists():
            raise ValueError(f"workspace already exists for run {run_id}")
        root.mkdir(parents=True, mode=0o700)

        excluded_top = None
        try:
            excluded_top = base.resolve().relative_to(source).parts[0]
        except (ValueError, IndexError):
            excluded_top = None

        def ignore(directory: str, names: list[str]) -> set[str]:
            ignored = {name for name in names if name in IGNORED}
            if Path(directory).resolve() == source and excluded_top:
                ignored.add(excluded_top)
            if Path(directory).resolve() == source:
                ignored.update(
                    name
                    for name in names
                    if name == store.path.name
                    or name.startswith(store.path.name + "-")
                )
            return ignored

        shutil.copytree(source, root / "repo", ignore=ignore)
        now = time.time()
        store.connection.execute(
            "INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                project_id,
                str(root),
                str(source),
                json.dumps(source_hashes(source, tracked_paths), sort_keys=True),
                json.dumps(asdict(plan), sort_keys=True),
                "ACTIVE",
                now,
                now,
                now + RETENTION_SECONDS,
            ),
        )
        store.connection.commit()
        return cls(store, run_id)

    @classmethod
    def load(cls, store: Store, run_id: str) -> Workspace:
        workspace = cls(store, run_id)
        if not workspace.repo.is_dir():
            raise ValueError(f"durable workspace is missing for run {run_id}")
        return workspace

    def metadata(self) -> dict[str, Any]:
        row = self.store.connection.execute(
            "SELECT * FROM workspaces WHERE run_id=?", (self.run_id,)
        ).fetchone()
        if not row:
            raise KeyError(self.run_id)
        result = dict(row)
        result["source_hashes"] = json.loads(result.pop("source_hashes_json"))
        result["plan"] = json.loads(result.pop("plan_json"))
        return result

    def assert_source_fresh(self) -> None:
        metadata = self.metadata()
        source = Path(metadata["source_root"])
        for relative, expected in metadata["source_hashes"].items():
            if digest(safe_path(source, relative)) != expected:
                raise RuntimeError(f"source changed since run checkpoint: {relative}")

    def checkpoint(
        self,
        component_id: str | None,
        state: dict[str, Any],
        report: dict[str, Any],
        paths: tuple[str, ...],
    ) -> str:
        sequence = self.store.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM checkpoints WHERE run_id=?",
            (self.run_id,),
        ).fetchone()["sequence"]
        identifier = uuid.uuid4().hex
        hashes = source_hashes(self.repo, paths)
        snapshot_root = self.root / "checkpoints" / str(sequence)
        staging = snapshot_root.with_name(f".{sequence}-{identifier}.tmp")
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.repo, staging / "repo", copy_function=_copy_on_write)
        staging.replace(snapshot_root)
        now = time.time()
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    self.run_id,
                    component_id,
                    sequence,
                    json.dumps(state, sort_keys=True),
                    json.dumps(hashes, sort_keys=True),
                    json.dumps(report),
                    now,
                ),
            )
            self.store.connection.execute(
                "UPDATE workspaces SET updated_at=? WHERE run_id=?", (now, self.run_id)
            )
        return identifier

    def restore_latest(self) -> dict[str, Any]:
        """Restore the last verified filesystem state, preserving later edits as evidence."""
        checkpoint = self.latest_checkpoint()
        if not checkpoint:
            raise RuntimeError("run has no verified checkpoint to resume")
        snapshot = self.root / "checkpoints" / str(checkpoint["sequence"]) / "repo"
        if not snapshot.is_dir():
            raise RuntimeError("verified checkpoint snapshot is missing")
        expected = checkpoint["hashes"]
        if source_hashes(snapshot, tuple(expected)) != expected:
            raise RuntimeError("verified checkpoint snapshot failed its hash check")
        dirty = self.root / "artifacts" / f"unverified-{time.time_ns()}"
        dirty.parent.mkdir(parents=True, exist_ok=True)
        self.repo.replace(dirty)
        try:
            shutil.copytree(snapshot, self.repo, copy_function=_copy_on_write)
        except Exception:
            dirty.replace(self.repo)
            raise
        return checkpoint

    def latest_checkpoint(self) -> dict[str, Any] | None:
        row = self.store.connection.execute(
            "SELECT * FROM checkpoints WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
            (self.run_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("state_json", "hashes_json", "report_json"):
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
        return result

    def mark(self, state: str) -> None:
        self.store.connection.execute(
            "UPDATE workspaces SET state=?, updated_at=? WHERE run_id=?",
            (state, time.time(), self.run_id),
        )
        self.store.connection.commit()

    @staticmethod
    def gc(store: Store, *, dry_run: bool = False, now: float | None = None) -> list[str]:
        rows = store.connection.execute(
            "SELECT run_id, root FROM workspaces WHERE state NOT IN ('ACTIVE', 'AWAITING_APPROVAL') "
            "AND expires_at IS NOT NULL AND expires_at < ?",
            (now or time.time(),),
        ).fetchall()
        removed = [row["run_id"] for row in rows]
        if not dry_run:
            for row in rows:
                root = Path(row["root"])
                allowed = workspace_base(store).resolve()
                if root.parent.resolve() == allowed:
                    shutil.rmtree(root, ignore_errors=True)
            store.connection.executemany(
                "DELETE FROM workspaces WHERE run_id=?", [(item,) for item in removed]
            )
            store.connection.commit()
        return removed


def idempotency_key(run_id: str, kind: str, payload: Any) -> str:
    encoded = json.dumps(
        {"run_id": run_id, "kind": kind, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _copy_on_write(source: str, destination: str) -> str:
    clone = getattr(os, "clonefile", None)
    if clone is not None:
        try:
            clone(source, destination)
            return destination
        except OSError:
            pass
    return shutil.copy2(source, destination)
