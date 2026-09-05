"""Local repository map and sparse evidence retrieval for small coding models."""

from __future__ import annotations

import ast
import hashlib
import re
import time
from pathlib import Path
from typing import Any

from .store import Store

EXTENSIONS = {
    ".c": "c",
    ".h": "c",
    ".js": "javascript",
    ".mjs": "javascript",
    ".ex": "elixir",
    ".exs": "elixir",
    ".heex": "heex",
    ".css": "css",
    ".py": "python",
    ".pyi": "python",
    ".scala": "scala",
    ".sbt": "scala",
    ".sql": "sql",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
}
IGNORED_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
SCALA_SYMBOL_RE = re.compile(
    r"^\s*(?:private\s+|protected\s+)?(?:case\s+)?(class|object|trait|def|val|var)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _python_symbols(content: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    result = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            line = content.splitlines()[node.lineno - 1].strip() if content.splitlines() else node.name
            result.append(
                {
                    "name": node.name,
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "start": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno),
                    "signature": line[:300],
                }
            )
    return result


def _scala_symbols(content: str) -> list[dict[str, Any]]:
    result = []
    for number, line in enumerate(content.splitlines(), 1):
        match = SCALA_SYMBOL_RE.match(line)
        if match:
            result.append(
                {"name": match.group(2), "kind": match.group(1), "start": number, "end": number, "signature": line.strip()[:300]}
            )
    return result


class RepositoryIndex:
    def __init__(self, store: Store, project_id: str, root: Path):
        self.store = store
        self.project_id = project_id
        self.root = root.resolve()

    def index(self) -> dict[str, int]:
        connection = self.store.connection
        indexed, unchanged = 0, 0
        seen = set()
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix not in EXTENSIONS or IGNORED_PARTS.intersection(path.parts):
                continue
            if path.stat().st_size > 512 * 1024:
                continue
            relative = str(path.relative_to(self.root))
            seen.add(relative)
            content = path.read_text(errors="replace")
            digest = _hash(content)
            row = connection.execute(
                "SELECT content_hash FROM repository_files WHERE project_id=? AND path=?",
                (self.project_id, relative),
            ).fetchone()
            if row and row["content_hash"] == digest:
                unchanged += 1
                continue
            connection.execute("DELETE FROM repository_symbols WHERE project_id=? AND path=?", (self.project_id, relative))
            connection.execute("DELETE FROM repository_fts WHERE project_id=? AND path=?", (self.project_id, relative))
            language = EXTENSIONS[path.suffix]
            symbols = _python_symbols(content) if language == "python" else _scala_symbols(content) if language == "scala" else []
            connection.executemany(
                "INSERT INTO repository_symbols VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(self.project_id, relative, item["name"], item["kind"], item["start"], item["end"], item["signature"]) for item in symbols],
            )
            connection.execute("INSERT INTO repository_fts(project_id, path, content) VALUES (?, ?, ?)", (self.project_id, relative, content))
            connection.execute(
                "INSERT INTO repository_files VALUES (?, ?, ?, ?, ?) ON CONFLICT(project_id, path) "
                "DO UPDATE SET content_hash=excluded.content_hash, language=excluded.language, indexed_at=excluded.indexed_at",
                (self.project_id, relative, digest, language, time.time()),
            )
            indexed += 1
        rows = connection.execute("SELECT path FROM repository_files WHERE project_id=?", (self.project_id,)).fetchall()
        for row in rows:
            if row["path"] not in seen:
                connection.execute("DELETE FROM repository_files WHERE project_id=? AND path=?", (self.project_id, row["path"]))
                connection.execute("DELETE FROM repository_symbols WHERE project_id=? AND path=?", (self.project_id, row["path"]))
                connection.execute("DELETE FROM repository_fts WHERE project_id=? AND path=?", (self.project_id, row["path"]))
        connection.commit()
        return {"indexed": indexed, "unchanged": unchanged, "files": len(seen)}

    def repo_map(self, *, limit: int = 80) -> str:
        rows = self.store.connection.execute(
            "SELECT path, name, kind, signature FROM repository_symbols WHERE project_id=? "
            "ORDER BY path, start_line LIMIT ?",
            (self.project_id, limit),
        ).fetchall()
        return "\n".join(f"{row['path']}:{row['kind']} {row['signature']}" for row in rows)

    def evidence(self, query: str, *, excluded: set[str] | None = None, limit: int = 4) -> str:
        excluded = excluded or set()
        tokens = list(dict.fromkeys(token.lower() for token in TOKEN_RE.findall(query)))[:16]
        if not tokens:
            return ""
        match = " OR ".join(f'"{token}"' for token in tokens)
        rows = self.store.connection.execute(
            "SELECT path, snippet(repository_fts, 2, '[', ']', ' … ', 24) AS snippet, rank "
            "FROM repository_fts WHERE repository_fts MATCH ? AND project_id=? ORDER BY rank LIMIT ?",
            (match, self.project_id, limit * 3),
        ).fetchall()
        cards = []
        for row in rows:
            if row["path"] in excluded:
                continue
            file_row = self.store.connection.execute(
                "SELECT content_hash FROM repository_files WHERE project_id=? AND path=?",
                (self.project_id, row["path"]),
            ).fetchone()
            source = (self.root / row["path"]).read_text(errors="replace")
            lines = source.splitlines()
            hit = next(
                (
                    number
                    for number, line in enumerate(lines)
                    if any(token in line.lower() for token in tokens)
                ),
                0,
            )
            start = max(0, hit - 5)
            end = min(len(lines), hit + 7)
            excerpt = "\n".join(
                f"{number:>5} | {lines[number - 1]}" for number in range(start + 1, end + 1)
            )
            cards.append(
                f"EVIDENCE {row['path']}:{start + 1}-{end} "
                f"hash={file_row['content_hash'][:12]} reason=lexical-repository-match\n"
                f"{excerpt or row['snippet']}"
            )
            if len(cards) == limit:
                break
        return "\n\n".join(cards)
