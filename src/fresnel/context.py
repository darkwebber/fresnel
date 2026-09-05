"""Token-budgeted context compilation with explainable evidence selection."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from .store import Store


@dataclass(frozen=True)
class ContextItem:
    kind: str
    content: str
    reason: str
    source: str
    priority: float = 1.0
    fresh: bool = True

    @property
    def tokens(self) -> int:
        return max(1, (len(self.content) + 3) // 4)

    @property
    def rendered_tokens(self) -> int:
        """Estimate the tokens consumed by this item in the rendered context."""
        return (len(self.render()) + 3) // 4

    def render(self) -> str:
        return (
            f"[{self.kind.upper()} source={self.source} "
            f"hash={self.source_hash[:12]}]\n{self.content}"
        )

    @property
    def source_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()


def compile_context(
    store: Store,
    run_id: str,
    component_id: str,
    attempt: int,
    budget_tokens: int,
    required: list[ContextItem],
    optional: list[ContextItem],
) -> tuple[str, dict[str, Any]]:
    """Select fresh evidence by utility per token after reserving required context."""
    included: list[ContextItem] = []
    omitted: list[dict[str, Any]] = []
    used = 0
    characters = 0

    def candidate_characters(item: ContextItem) -> int:
        return characters + (2 if included else 0) + len(item.render())

    for item in required:
        if not item.fresh:
            raise ValueError(f"required context is stale: {item.source}")
        if (candidate_characters(item) + 3) // 4 > budget_tokens:
            raise ValueError("required component context exceeds the input token budget")
        characters = candidate_characters(item)
        included.append(item)
        used = (characters + 3) // 4
    ranked = sorted(
        (item for item in optional if item.content.strip()),
        key=lambda item: (item.fresh, item.priority / max(1, item.rendered_tokens)),
        reverse=True,
    )
    for item in ranked:
        if not item.fresh:
            omitted.append(
                {
                    "kind": item.kind,
                    "source": item.source,
                    "reason": "stale",
                    "tokens": item.rendered_tokens,
                    "priority": item.priority,
                    "source_hash": item.source_hash,
                    "fresh": False,
                }
            )
        elif (candidate_characters(item) + 3) // 4 <= budget_tokens:
            characters = candidate_characters(item)
            included.append(item)
            used = (characters + 3) // 4
        else:
            omitted.append(
                {
                    "kind": item.kind,
                    "source": item.source,
                    "reason": "budget",
                    "tokens": item.rendered_tokens,
                    "priority": item.priority,
                    "source_hash": item.source_hash,
                    "fresh": True,
                }
            )
    items = [
        {
            **{key: value for key, value in asdict(item).items() if key != "content"},
            "tokens": item.rendered_tokens,
            "source_hash": item.source_hash,
            "included": True,
        }
        for item in included
    ] + [{**item, "included": False} for item in omitted]
    identifier = uuid.uuid4().hex
    manifest = {
        "id": identifier,
        "budget_tokens": budget_tokens,
        "used_tokens": used,
        "items": items,
    }
    store.connection.execute(
        "INSERT INTO context_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            identifier,
            run_id,
            component_id,
            attempt,
            budget_tokens,
            used,
            json.dumps(items),
            time.time(),
        ),
    )
    store.connection.commit()
    rendered = "\n\n".join(
        item.render()
        for item in included
    )
    return rendered, manifest
