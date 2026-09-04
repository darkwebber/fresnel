"""Lazy, policy-bound capabilities for local coding workers."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .protocol import Component
from .references import exa_reference, file_excerpt_reference, help_reference, pydoc_reference
from .repository import RepositoryIndex
from .sandbox import clean_environment
from .sandbox import command as sandbox_command
from .store import Store

CAPABILITIES = {
    "repository_map": "List relevant project symbols without reading entire files.",
    "symbol_search": "Find bounded repository evidence for an implementation intent.",
    "file_excerpt": "Read a precise line range from an authorized file.",
    "local_docs": "Inspect installed Python documentation.",
    "help_command": "Run a local command's help mode.",
    "test_execution": "Run a declared validation command in the isolated workspace.",
    "environment": "Read non-secret runtime and dependency metadata.",
    "exa": "Search authorized domains for a technical reference.",
}


def discover(intent: str) -> list[dict[str, str]]:
    words = {word.lower() for word in intent.replace("_", " ").split()}
    scored = []
    for name, description in CAPABILITIES.items():
        score = len(words.intersection((name + " " + description).lower().split()))
        scored.append((score, name, description))
    return [
        {"name": name, "description": description}
        for _score, name, description in sorted(scored, reverse=True)[:3]
    ]


def _card(capability: str, intent: str, source: str, content: str) -> dict[str, Any]:
    content = content[-12000:]
    return {
        "capability": capability,
        "intent": intent,
        "source": source,
        "content": content,
        "source_hash": hashlib.sha256(content.encode()).hexdigest(),
        "fresh_at": time.time(),
        "continuation": None,
    }


class CapabilityBroker:
    def __init__(
        self,
        store: Store,
        run_id: str,
        component: Component,
        root: Path,
        repository: RepositoryIndex,
        *,
        python: str | None = None,
        exa_key: str | None = None,
    ):
        self.store = store
        self.run_id = run_id
        self.component = component
        self.root = root.resolve()
        self.repository = repository
        self.python = python
        self.exa_key = exa_key

    def resolve(self, request: dict[str, Any]) -> dict[str, Any]:
        capability = str(request.get("capability") or request.get("kind") or "")
        intent = str(request.get("intent") or request.get("query") or capability)
        identifier = hashlib.sha256(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "component": self.component.id,
                    "request": request,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        prior = self.store.connection.execute(
            "SELECT result_json FROM capability_calls WHERE id=?", (identifier,)
        ).fetchone()
        if prior:
            return {"id": identifier, **json.loads(prior["result_json"]), "replayed": True}
        if capability == "discover":
            result = _card(capability, intent, "fresnel://capabilities", json.dumps(discover(intent)))
        elif capability == "repository_map":
            result = _card(capability, intent, "repository-index", self.repository.repo_map())
        elif capability == "symbol_search":
            result = _card(capability, intent, "repository-index", self.repository.evidence(intent))
        elif capability == "file_excerpt":
            record = file_excerpt_reference(
                self.root,
                request,
                set(self.component.targets + self.component.context),
            )
            query = record["query"]
            result = _card(
                capability,
                intent,
                f"file:{query['path']}:{query['start_line']}-{query['end_line']}",
                record["content"],
            )
        elif capability == "local_docs":
            record = pydoc_reference(str(request.get("query", intent)), python=self.python)
            result = _card(capability, intent, f"pydoc:{record['query']}", record["content"])
        elif capability == "help_command":
            argv = tuple(str(value) for value in request.get("argv", []))
            if argv not in self.component.references.help_commands:
                raise ValueError("help command must match an orchestrator-declared argv array")
            record = help_reference(list(argv), self.root)
            result = _card(
                capability, intent, "help:" + " ".join(record["query"]), record["content"]
            )
        elif capability == "test_execution":
            argv = tuple(str(value) for value in request.get("argv", []))
            if argv not in self.component.validation:
                raise ValueError("test execution must match a declared validation command")
            completed = subprocess.run(
                sandbox_command(self.root, argv),
                cwd=self.root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=min(120, self.component.budgets.wall_seconds),
                env=clean_environment(self.root),
                check=False,
            )
            result = _card(
                capability,
                intent,
                "validation:" + " ".join(argv),
                f"exit_code={completed.returncode}\n{completed.stdout[-8000:]}",
            )
        elif capability == "environment":
            names = sorted(path.name for path in self.root.iterdir())[:200]
            result = _card(
                capability,
                intent,
                "local-environment",
                json.dumps({"python": self.python, "workspace_entries": names}),
            )
        elif capability == "exa":
            if self.component.risk.network != "reference-only" or not self.exa_key:
                raise PermissionError("web reference capability is not authorized")
            domains = list(request.get("include_domains", []))
            if not domains:
                raise ValueError("web references require include_domains")
            authorized = {
                str(domain)
                for query in self.component.references.web_queries
                for domain in query.get("include_domains", [])
            }
            if not authorized or not set(domains).issubset(authorized):
                raise PermissionError("requested web domains are outside the component envelope")
            record = exa_reference(str(request.get("query", intent)), self.exa_key, domains)
            result = _card(
                capability,
                intent,
                "exa:" + ",".join(domains),
                json.dumps(record["results"], indent=2),
            )
        else:
            raise ValueError(f"unknown capability: {capability}")
        self.store.connection.execute(
            "INSERT INTO capability_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identifier,
                self.run_id,
                self.component.id,
                capability,
                intent,
                json.dumps(request),
                json.dumps(result),
                time.time(),
            ),
        )
        self.store.connection.commit()
        return {"id": identifier, **result}
