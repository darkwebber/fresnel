"""Fresnel planning, component execution, validation, assembly, and reporting."""

from __future__ import annotations

import difflib
import hashlib
import json
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path

from .approvals import decide
from .budget import allocate
from .capabilities import CapabilityBroker
from .config import Config, environment_key
from .context import ContextItem, compile_context
from .hardware import memory_free_percent
from .learning import classify_failure, signature
from .memory import Memory
from .protocol import Component, Plan, parse_plan, safe_path
from .references import (
    exa_reference,
    help_reference,
    pydoc_reference,
    render_packet,
)
from .repository import RepositoryIndex
from .router import shadow_route
from .sandbox import clean_environment
from .sandbox import command as sandbox_command
from .store import Store
from .worker import (
    WorkerTruncated,
    apply_operations,
    operations_already_applied,
    render_prompt,
)
from .worker import call as call_worker
from .worker import parse as parse_worker
from .workspace import Workspace, idempotency_key

IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
COORDINATOR_SYSTEM = """You are Fresnel's planning controller. Own architecture, decomposition,
contracts, algorithms, validation, and final review. Spark is a bounded 4B implementation worker.
Return JSON only and never ask Spark to discover architecture."""


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _copy_repo(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in IGNORED}

    shutil.copytree(source, destination, ignore=ignore, dirs_exist_ok=True)


def _inventory(repo: Path, limit: int = 2000) -> list[str]:
    result = []
    for path in repo.rglob("*"):
        if path.is_file() and not any(part in IGNORED for part in path.relative_to(repo).parts):
            result.append(str(path.relative_to(repo)))
            if len(result) >= limit:
                break
    return sorted(result)


def _api_json(
    endpoint: str, model: str, key: str | None, messages: list[dict], max_tokens: int
) -> tuple[dict, dict]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    def send() -> dict:
        request = urllib.request.Request(
            endpoint, json.dumps(payload).encode(), headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)

    try:
        body = send()
    except urllib.error.HTTPError as exc:
        if exc.code not in (400, 404, 422):
            raise
        payload.pop("response_format", None)
        body = send()
    content = body["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(content), body.get("usage", {})


def plan_request(
    request: str, repo: Path, endpoint: str, model: str, key: str | None
) -> tuple[Plan, list[dict]]:
    listing = _inventory(repo)
    inspect_message = {
        "role": "user",
        "content": f"""REQUEST:\n{request}\n\nFILES:\n{json.dumps(listing)}
Return {{"inspect":["relative/path"]}} selecting at most 20 files needed to design the change.""",
    }
    selection, usage1 = _api_json(
        endpoint,
        model,
        key,
        [{"role": "system", "content": COORDINATOR_SYSTEM}, inspect_message],
        1000,
    )
    selected = list(dict.fromkeys(selection.get("inspect", [])))
    if len(selected) > 20:
        raise ValueError("coordinator selected more than 20 files")
    evidence = []
    used = 0
    for relative in selected:
        path = safe_path(repo, relative)
        if not path.is_file():
            raise ValueError(f"coordinator selected missing file: {relative}")
        block = f'FILE "{relative}"\n{path.read_text(errors="replace")}'
        if used + len(block) > 100000:
            break
        evidence.append(block)
        used += len(block)
    schema = {
        "protocol_version": "1.1",
        "objective": "outcome",
        "scope": ["file.py"],
        "acceptance": ["observable end-to-end result"],
        "constraints": ["project-wide invariant"],
        "interfaces": ["public interface contract"],
        "invariants": ["cross-component invariant"],
        "contracts": [{"path": "test_contract.py", "content": "small executable contract"}],
        "components": [
            {
                "id": "component",
                "task": "bounded task",
                "depends_on": [],
                "targets": ["file.py"],
                "context": ["test_contract.py"],
                "constraints": ["invariant"],
                "acceptance": ["observable result"],
                "implementation": ["specific algorithm"],
                "validation": [["python3", "-m", "unittest", "-v"]],
                "risk_envelope": {
                    "write_paths": ["file.py"],
                    "network": "none",
                    "installs": False,
                    "external_writes": False,
                },
                "budgets": {
                    "max_capability_calls": 8,
                    "max_edit_attempts": 3,
                    "wall_seconds": 300,
                },
                "references": {
                    "local_docs": [],
                    "help_commands": [],
                    "web_queries": [],
                    "allow_worker_web": False,
                },
            }
        ],
        "integration_validation": [["python3", "-m", "unittest", "-v"]],
        "review_checklist": ["semantic review item"],
    }
    message = {
        "role": "user",
        "content": f"""REQUEST:\n{request}\n\nEVIDENCE:\n{chr(10).join(evidence)}
Return an ordered protocol-v1 plan matching this shape:\n{json.dumps(schema)}
Write focused contract tests only for greenfield behavior. Never overwrite existing tests.
Dependencies may reference only earlier components. Give Spark explicit algorithms and state representations.
Use local docs before domain-restricted Exa for uncertain APIs. Validation uses argv arrays without shell syntax.""",
    }
    raw_plan, usage2 = _api_json(
        endpoint, model, key, [{"role": "system", "content": COORDINATOR_SYSTEM}, message], 6000
    )
    return parse_plan(raw_plan), [
        {"stage": "inspection", "usage": usage1},
        {"stage": "plan", "usage": usage2},
    ]


def _project_python(repo: Path) -> str | None:
    return next(
        (
            str(path)
            for path in (repo / ".venv/bin/python", repo / "venv/bin/python")
            if path.is_file()
        ),
        None,
    )


def _validation(
    root: Path,
    commands: tuple[tuple[str, ...], ...],
    timeout: int = 120,
    python: str | None = None,
) -> tuple[bool, list[dict]]:
    results = []
    for command in commands:
        started = time.perf_counter()
        try:
            requested = list(command)
            if python and Path(requested[0]).name in {"python", "python3"}:
                requested[0] = python
            executed = _sandboxed_command(root, tuple(requested))
            completed = subprocess.run(
                executed,
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                env=clean_environment(root),
                check=False,
            )
            result = {
                "command": list(command),
                "exit_code": completed.returncode,
                "sandboxed": executed[0] == "/usr/bin/sandbox-exec",
                "seconds": round(time.perf_counter() - started, 3),
                "output": completed.stdout[-6000:],
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                "command": list(command),
                "exit_code": None,
                "seconds": round(time.perf_counter() - started, 3),
                "output": f"TIMEOUT\n{(exc.stdout or '')[-5000:]}",
            }
        results.append(result)
        if result["exit_code"] != 0:
            return False, results
    return True, results


def _sandboxed_command(root: Path, command: tuple[str, ...]) -> list[str]:
    return sandbox_command(root, command) if platform.system() == "Darwin" else list(command)


def _references(
    component: Component, root: Path, exa_key: str | None, project_python: str | None = None
) -> tuple[list[dict], str]:
    records = [
        pydoc_reference(symbol, python=project_python) for symbol in component.references.local_docs
    ]
    records.extend(
        help_reference(list(command), root) for command in component.references.help_commands
    )
    for spec in component.references.web_queries:
        if not exa_key:
            raise RuntimeError("component requires Exa but no Exa key is configured")
        records.append(
            exa_reference(str(spec["query"]), exa_key, list(spec.get("include_domains", [])))
        )
    return records, render_packet(records)


def _diff(original: Path, work: Path, paths: tuple[str, ...]) -> str:
    files = []
    for relative in paths:
        before_path, after_path = safe_path(original, relative), safe_path(work, relative)
        before_exists, after_exists = before_path.is_file(), after_path.is_file()
        before = before_path.read_text().splitlines(keepends=True) if before_exists else []
        after = after_path.read_text().splitlines(keepends=True) if after_exists else []
        chunks = list(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{relative}" if before_exists else "/dev/null",
                tofile=f"b/{relative}" if after_exists else "/dev/null",
            )
        )
        if chunks:
            files.append("".join(chunks).rstrip() + "\n")
    return "\n".join(files)


def _metrics(report: dict, config: Config) -> dict:
    attempts = [attempt for component in report["components"] for attempt in component["attempts"]]
    coordinator_calls = report.get("coordinator_calls", [])
    coordinator_prompt = sum(call["usage"].get("prompt_tokens", 0) for call in coordinator_calls)
    coordinator_completion = sum(
        call["usage"].get("completion_tokens", 0) for call in coordinator_calls
    )
    estimated_cost = (
        coordinator_prompt * config.coordinator_input_cost_per_million
        + coordinator_completion * config.coordinator_output_cost_per_million
    ) / 1_000_000
    worker_seconds = round(sum(a.get("seconds", 0) for a in attempts), 3)
    return {
        "quality_gate_passed": report["success"],
        "components_completed": sum(component["success"] for component in report["components"]),
        "components_planned": len(report["plan"]["components"]),
        "coordinator_prompt_tokens": coordinator_prompt,
        "coordinator_completion_tokens": coordinator_completion,
        "estimated_coordinator_cost_usd": round(estimated_cost, 6),
        "worker_attempts": len(attempts),
        "worker_truncation_retries": sum(
            "WorkerTruncated" in attempt.get("error", "") for attempt in attempts
        ),
        "worker_reference_reads": sum(
            attempt.get("approval", {}).get("request", {}).get("kind") == "file_excerpt"
            for attempt in attempts
        ),
        "worker_pressure_events": sum(
            attempt.get("budget", {}).get("pressure") in {"moderate", "high", "critical"}
            for attempt in attempts
        ),
        "worker_prompt_tokens": sum(a.get("usage", {}).get("prompt_tokens", 0) for a in attempts),
        "worker_cached_tokens": sum(
            a.get("usage", {}).get("prompt_tokens_details", {}).get("cached_tokens", 0)
            for a in attempts
        ),
        "worker_completion_tokens": sum(
            a.get("usage", {}).get("completion_tokens", 0) for a in attempts
        ),
        "worker_model_id_fallbacks": sum(
            bool(a.get("usage", {}).get("model_id_fallback")) for a in attempts
        ),
        "worker_seconds": worker_seconds,
        "successful_components_per_worker_minute": round(
            60 * sum(component["success"] for component in report["components"]) / worker_seconds, 3
        )
        if worker_seconds
        else None,
    }


def run(
    repo: Path,
    plan: Plan,
    config: Config,
    *,
    request: str = "",
    apply: bool = False,
    decisions: dict[str, str] | None = None,
    coordinator_calls: list[dict] | None = None,
    store: Store | None = None,
    progress: Callable[[dict], None] | None = None,
    resume_run_id: str | None = None,
) -> dict:
    repo = repo.resolve()
    decisions = decisions or {}
    store = store or Store()
    memory = Memory(store)
    resumed = resume_run_id is not None
    run_id = resume_run_id or store.new_run(request or plan.objective, config.active_worker)
    progress_callback = progress or (lambda _event: None)
    progress_history: list[dict] = []

    def report_progress(event: dict) -> None:
        snapshot = dict(event)
        progress_history.append(snapshot)
        store.progress_event(run_id, snapshot)
        progress_callback(snapshot)

    progress = report_progress
    run_started = time.perf_counter()
    component_seconds: list[float] = []
    progress(
        {
            "state": "started",
            "phase": "workspace",
            "label": "Restoring verified workspace" if resumed else "Preparing durable workspace",
            "run_id": run_id,
            "progress": 0,
            "total": len(plan.components),
            "eta_seconds": None,
        }
    )
    if not store.run(run_id):
        raise ValueError(f"unknown run: {run_id}")
    if resumed:
        store.clear_cancel(run_id)
    targets = tuple(
        dict.fromkeys(path for component in plan.components for path in component.targets)
    )
    contracts = tuple(contract.path for contract in plan.contracts)
    assembled = tuple(dict.fromkeys(targets + contracts))
    tracked = tuple(
        dict.fromkeys(
            assembled
            + tuple(path for component in plan.components for path in component.context)
        )
    )
    project_identifier, _project_root = memory.ensure_project(repo)
    if resumed:
        workspace = Workspace.load(store, run_id)
        workspace.assert_source_fresh()
        metadata = workspace.metadata()
        if json.dumps(metadata["plan"], sort_keys=True) != json.dumps(asdict(plan), sort_keys=True):
            raise ValueError("resume plan does not match the persisted run plan")
        hashes = metadata["source_hashes"]
    else:
        store.event(run_id, "PLANNED", {"objective": plan.objective})
        memory.create_charter(
            run_id,
            repo,
            plan.objective,
            list(plan.acceptance),
            list(plan.constraints),
            list(plan.scope),
        )
        memory.event(
            "TASK_STARTED",
            {
                "components": [component.id for component in plan.components],
                "invariants": list(plan.review_checklist + plan.invariants),
            },
            repo=repo,
            run_id=run_id,
        )
        hashes = {path: _digest(safe_path(repo, path)) for path in assembled}
        workspace = Workspace.create(
            store, run_id, project_identifier, repo, plan, tracked
        )
    profile = config.selected_profile
    project_python = _project_python(repo)
    checkpoint = workspace.restore_latest() if resumed else None
    report = checkpoint["report"] if checkpoint else {
        "protocol_version": plan.protocol_version,
        "run_id": run_id,
        "objective": plan.objective,
        "success": False,
        "applied": False,
        "plan": asdict(plan),
        "coordinator_calls": coordinator_calls or [],
        "router": shadow_route({"targets": list(targets)}),
        "components": [],
        "integration_validation": [],
        "notifications": [],
        "progress": progress_history,
        "diff": "",
        "worker_model": config.model_path or config.model_repo,
    }
    if resumed:
        prior_progress = list(report.get("progress", []))
        progress_history[:] = prior_progress + progress_history
        report["progress"] = progress_history
        report["success"] = False
        report["status"] = "RESUMING"
    try:
        with nullcontext(workspace.repo) as work:
            repository_index = RepositoryIndex(store, project_identifier, work)
            index_metrics = repository_index.index()
            report["memory"] = {"repository_index": index_metrics}
            progress(
                {
                    "state": "updated",
                    "phase": "workspace",
                    "label": f"Workspace ready · indexed {index_metrics['files']} files",
                    "run_id": run_id,
                    "progress": 0,
                    "total": len(plan.components),
                    "eta_seconds": None,
                }
            )
            if not resumed:
                for contract in plan.contracts:
                    path = safe_path(work, contract.path)
                    if path.exists():
                        raise ValueError(
                            f"contract would overwrite existing file: {contract.path}"
                        )
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(contract.content)
                workspace.checkpoint(
                    None,
                    {"phase": "prepared", "completed": []},
                    report,
                    assembled,
                )
            exa_key = (
                environment_key("EXA_API_KEY", "exa-api-key") if config.exa_enabled else None
            )
            completed_components = {
                item["id"] for item in report["components"] if item.get("success")
            }
            for component_index, component in enumerate(plan.components, 1):
                if component.id in completed_components:
                    progress(
                        {
                            "state": "updated",
                            "phase": "component",
                            "label": f"Restored verified component {component.id}",
                            "run_id": run_id,
                            "component_id": component.id,
                            "progress": component_index,
                            "total": len(plan.components),
                            "eta_seconds": None,
                        }
                    )
                    continue
                if store.cancelled(run_id):
                    raise RuntimeError("run cancelled")
                component_started = time.perf_counter()
                remaining = len(plan.components) - component_index + 1
                eta = (
                    round(sum(component_seconds) / len(component_seconds) * remaining)
                    if component_seconds
                    else None
                )
                progress(
                    {
                        "state": "updated",
                        "phase": "component",
                        "label": f"Component {component_index}/{len(plan.components)} · {component.id}",
                        "run_id": run_id,
                        "component_id": component.id,
                        "progress": component_index - 1,
                        "total": len(plan.components),
                        "eta_seconds": eta,
                    }
                )
                store.event(run_id, "COMPONENT_RUNNING", {"component_id": component.id})
                memory.event(
                    "COMPONENT_STARTED",
                    {"component_id": component.id, "task": component.task},
                    repo=repo,
                    run_id=run_id,
                )
                if plan.protocol_version == "1.0":
                    records, packet = _references(component, work, exa_key, project_python)
                else:
                    records, packet = [], ""
                query = "\n".join(
                    (component.task, *component.implementation, *component.acceptance)
                )
                retrieved = repository_index.evidence(
                    query, excluded=set(component.targets + component.context)
                )
                repo_map = repository_index.repo_map(limit=60)
                memory_context = "\n\n".join(
                    part for part in ("REPOSITORY MAP\n" + repo_map if repo_map else "", retrieved) if part
                )
                packet = "\n\n".join(part for part in (packet, memory_context) if part)
                component_result = {
                    "id": component.id,
                    "success": False,
                    "references": records,
                    "attempts": [],
                    "capability_calls": [],
                    "context_manifests": [],
                }
                broker = CapabilityBroker(
                    store,
                    run_id,
                    component,
                    work,
                    repository_index,
                    python=project_python,
                    exa_key=exa_key,
                )
                feedback = ""
                number = 1
                capability_count = 0
                edit_limit = min(profile.max_attempts, component.budgets.max_edit_attempts)
                capability_limit = min(
                    profile.max_capability_calls, component.budgets.max_capability_calls
                )
                while number <= edit_limit:
                    if time.perf_counter() - component_started > component.budgets.wall_seconds:
                        component_result["status"] = "BUDGET_EXHAUSTED"
                        break
                    if store.cancelled(run_id):
                        raise RuntimeError("run cancelled")
                    progress(
                        {
                            "state": "updated",
                            "phase": "worker",
                            "label": (
                                f"Spark implementing {component.id} · "
                                f"attempt {number}/{edit_limit}"
                            ),
                            "run_id": run_id,
                            "component_id": component.id,
                            "attempt": number,
                            "progress": component_index - 1,
                            "total": len(plan.components),
                            "eta_seconds": eta,
                        }
                    )
                    state_row = store.connection.execute(
                        "SELECT state_json FROM task_state WHERE run_id=?", (run_id,)
                    ).fetchone()
                    situation = state_row["state_json"] if state_row else ""
                    playbook_rows = store.connection.execute(
                        "SELECT trigger, rule FROM playbooks WHERE status='ACTIVE' "
                        "AND (LOWER(trigger) LIKE ? OR LOWER(rule) LIKE ?) "
                        "ORDER BY updated_at DESC LIMIT 3",
                        (f"%{component.id.lower()}%", f"%{component.task.lower()[:40]}%"),
                    ).fetchall()
                    playbooks = "\n".join(
                        f"- IF {row['trigger']} THEN {row['rule']}" for row in playbook_rows
                    )
                    initial_budget = allocate(
                        profile,
                        memory_free_percent=memory_free_percent(),
                        attempt=number,
                    )
                    profile_facts = memory.profile(repo)
                    influenced = report["memory"].setdefault("influenced_facts", [])
                    for fact in profile_facts[:8]:
                        if fact["id"] not in influenced:
                            influenced.append(fact["id"])
                    facts_text = "\n".join(
                        f"- {item['kind']}: {item['value']['value']}"
                        for item in profile_facts[:8]
                    )
                    compiled, manifest = compile_context(
                        store,
                        run_id,
                        component.id,
                        number,
                        max(512, initial_budget.max_input_tokens // 3),
                        [
                            ContextItem(
                                "working-state",
                                situation or "fresh component",
                                "deterministic current task state",
                                "fresnel://task-state",
                                10,
                            )
                        ],
                        [
                            ContextItem(
                                "evidence",
                                packet,
                                "repository and reference evidence",
                                "fresnel://evidence",
                                6,
                            ),
                            ContextItem(
                                "playbook",
                                playbooks,
                                "matching validated procedure",
                                "fresnel://playbooks",
                                5,
                            ),
                            ContextItem(
                                "user-memory",
                                facts_text,
                                "confirmed local preferences",
                                "fresnel://profile",
                                4,
                            ),
                        ],
                    )
                    component_result["context_manifests"].append(manifest)
                    prompt = render_prompt(
                        component,
                        work,
                        compiled,
                        feedback,
                        goal=plan.objective,
                        max_input_tokens=initial_budget.max_input_tokens,
                        response_budget=initial_budget.max_output_tokens,
                        attempt=number,
                        situation="",
                        playbooks="",
                    )
                    estimated_tokens = (len(prompt) + 3) // 4
                    budget = allocate(
                        profile,
                        estimated_input_tokens=estimated_tokens,
                        memory_free_percent=initial_budget.memory_free_percent,
                        attempt=number,
                    )
                    if estimated_tokens > budget.max_input_tokens:
                        raise ValueError(
                            f"component {component.id} prompt is approximately {estimated_tokens} tokens; "
                            f"decompose it below the {budget.max_input_tokens}-token pressure-adjusted limit"
                        )
                    started = time.perf_counter()
                    output = ""
                    usage = {}
                    try:
                        memory.event(
                            "WORKER_CALL_STARTED",
                            {"component_id": component.id, "attempt": number},
                            repo=repo,
                            run_id=run_id,
                        )
                        output, usage = call_worker(
                            f"http://{config.host}:{config.port}/v1/chat/completions",
                            config.model_path or config.model_repo,
                            prompt,
                            budget.max_output_tokens,
                            temperature=profile.temperature,
                            top_p=profile.top_p,
                            top_k=profile.top_k,
                            min_p=profile.min_p,
                        )
                        elapsed = round(time.perf_counter() - started, 3)
                        output_blob = memory.put_blob("worker_output", output) if output else None
                        attempt = {
                            "attempt": number,
                            "seconds": elapsed,
                            "usage": usage,
                            "raw_output": output if len(output) <= 4096 else output[:4096],
                            "output_blob": output_blob,
                            "raw_output_truncated": len(output) > 4096,
                        }
                        fallback = component.targets[0] if len(component.targets) == 1 else None
                        kind, payload = parse_worker(output, fallback_target=fallback)
                        memory.event(
                            "WORKER_CALL_COMPLETED",
                            {
                                "component_id": component.id,
                                "attempt": number,
                                "output_blob": output_blob,
                                "operation_kind": kind,
                            },
                            repo=repo,
                            run_id=run_id,
                        )
                        progress(
                            {
                                "state": "updated",
                                "phase": "worker",
                                "label": f"Spark answered for {component.id} · {elapsed}s",
                                "run_id": run_id,
                                "component_id": component.id,
                                "attempt": number,
                                "progress": component_index - 1,
                                "total": len(plan.components),
                                "eta_seconds": eta,
                            }
                        )
                    except Exception as exc:
                        if isinstance(exc, WorkerTruncated):
                            output = exc.content
                            usage = exc.usage
                        elapsed = round(time.perf_counter() - started, 3)
                        details = f"{type(exc).__name__}: {exc}"
                        category = classify_failure(details)
                        store.record_failure(
                            run_id,
                            component.id,
                            signature(category, details),
                            category,
                            {"attempt": number, "error": details},
                        )
                        output_blob = memory.put_blob("worker_output", output) if output else None
                        component_result["attempts"].append(
                            {
                                "attempt": number,
                                "seconds": elapsed,
                                "usage": usage,
                                "raw_output": output if len(output) <= 4096 else output[:4096],
                                "output_blob": output_blob,
                                "raw_output_truncated": len(output) > 4096,
                                "error": details,
                                "budget": asdict(budget),
                            }
                        )
                        memory.event(
                            "WORKER_FAILED",
                            {
                                "component_id": component.id,
                                "attempt": number,
                                "error": details,
                                "output_blob": output_blob,
                            },
                            repo=repo,
                            run_id=run_id,
                        )
                        progress(
                            {
                                "state": "updated",
                                "phase": "retry",
                                "label": f"Retrying {component.id} · {details}",
                                "run_id": run_id,
                                "component_id": component.id,
                                "attempt": number,
                                "progress": component_index - 1,
                                "total": len(plan.components),
                                "eta_seconds": eta,
                            }
                        )
                        if isinstance(exc, WorkerTruncated):
                            feedback = (
                                "Previous output hit the token limit. Do not repeat prose or unchanged code. "
                                "Use the smallest exact SEARCH/REPLACE operations that fully complete the task. "
                                "If required file content is omitted, request one narrow file_excerpt first."
                            )
                        else:
                            feedback = (
                                f"Previous response was unusable: {details}. "
                                "Return valid bounded operations only."
                            )
                        number += 1
                        continue
                    if store.cancelled(run_id):
                        raise RuntimeError("run cancelled")
                    if kind in {"capability", "reference", "action"}:
                        if kind == "reference":
                            payload["capability"] = payload.get("kind")
                        approval = decide(
                            component.id,
                            payload,
                            decisions,
                            web_authorized=(
                                component.risk.network == "reference-only" and bool(exa_key)
                            ),
                        )
                        attempt["approval"] = approval
                        component_result["attempts"].append(attempt)
                        if approval["decision"] == "escalate":
                            report["notifications"].append(approval)
                            component_result["status"] = "AWAITING_APPROVAL"
                            progress(
                                {
                                    "state": "updated",
                                    "phase": "approval",
                                    "label": f"User approval needed for {component.id}",
                                    "run_id": run_id,
                                    "component_id": component.id,
                                    "progress": component_index - 1,
                                    "total": len(plan.components),
                                    "eta_seconds": None,
                                }
                            )
                            break
                        if approval["decision"] == "deny":
                            feedback = (
                                f"Action denied: {approval['reason']}. Use an in-scope alternative."
                            )
                            continue
                        if kind == "action" and "capability" not in payload:
                            feedback = "Action approved by policy; use only the existing bounded operations."
                            continue
                        if capability_count >= capability_limit:
                            feedback = "Capability budget exhausted; finish from verified evidence or report a blocker."
                            number += 1
                            continue
                        capability_count += 1
                        memory.event(
                            "CAPABILITY_STARTED",
                            {"component_id": component.id, "request": payload},
                            repo=repo,
                            run_id=run_id,
                        )
                        capability = broker.resolve(payload)
                        memory.event(
                            "CAPABILITY_COMPLETED",
                            {
                                "component_id": component.id,
                                "capability_id": capability["id"],
                                "source_hash": capability["source_hash"],
                            },
                            repo=repo,
                            run_id=run_id,
                        )
                        component_result["capability_calls"].append(capability)
                        packet = "\n\n".join(
                            part
                            for part in (
                                packet,
                                (
                                    f"CAPABILITY {capability['capability']} "
                                    f"source={capability['source']} "
                                    f"hash={capability['source_hash'][:12]}\n"
                                    f"{capability['content']}"
                                ),
                            )
                            if part
                        )
                        continue
                    try:
                        operation_key = idempotency_key(
                            run_id,
                            "edit",
                            {
                                "component": component.id,
                                "attempt": number,
                                "operations": payload,
                            },
                        )
                        prior_operation = store.idempotency_result(operation_key)
                        if prior_operation is None:
                            interrupted_operation = store.idempotency_state(operation_key) == "STARTED"
                            store.idempotency_start(
                                operation_key,
                                run_id,
                                "edit",
                                {"component": component.id, "operations": payload},
                            )
                            memory.event(
                                "EDIT_STARTED",
                                {
                                    "component_id": component.id,
                                    "idempotency_key": operation_key,
                                },
                                repo=repo,
                                run_id=run_id,
                            )
                            if interrupted_operation and operations_already_applied(
                                work, set(component.targets), payload
                            ):
                                changed_paths = sorted(
                                    {operation["path"] for operation in payload}
                                )
                            else:
                                changed_paths = apply_operations(
                                    work,
                                    set(component.targets),
                                    payload,
                                    replace_existing_create=True,
                                )
                            store.idempotency_finish(
                                operation_key, {"paths": changed_paths}
                            )
                        else:
                            changed_paths = prior_operation.get("paths", [])
                    except (ValueError, OSError) as exc:
                        details = f"{type(exc).__name__}: {exc}"
                        category = classify_failure(details)
                        attempt.update({"passed": False, "operation_error": details})
                        component_result["attempts"].append(attempt)
                        store.record_call(run_id, component.id, usage, attempt["seconds"], False)
                        store.record_failure(
                            run_id,
                            component.id,
                            signature(category, details),
                            category,
                            {"attempt": number, "error": details},
                        )
                        feedback = (
                            f"Operation rejected: {details}. Existing targets require EDIT with "
                            "one unique exact SEARCH block; missing targets require CREATE."
                        )
                        number += 1
                        continue
                    memory.event(
                        "EDIT_APPLIED",
                        {
                            "component_id": component.id,
                            "paths": changed_paths,
                            "idempotency_key": operation_key,
                        },
                        repo=repo,
                        run_id=run_id,
                    )
                    progress(
                        {
                            "state": "updated",
                            "phase": "validation",
                            "label": f"Validating {component.id}",
                            "run_id": run_id,
                            "component_id": component.id,
                            "progress": component_index - 1,
                            "total": len(plan.components),
                            "eta_seconds": eta,
                        }
                    )
                    memory.event(
                        "VALIDATION_STARTED",
                        {"component_id": component.id, "commands": component.validation},
                        repo=repo,
                        run_id=run_id,
                    )
                    passed, validation = _validation(
                        work, component.validation, python=project_python
                    )
                    attempt.update({"passed": passed, "validation": validation})
                    manifest["usefulness"] = 1.0 if passed else 0.25
                    manifest["outcome"] = "validation_passed" if passed else "validation_failed"
                    store.context_feedback(
                        manifest["id"], manifest["usefulness"], manifest["outcome"]
                    )
                    attempt["budget"] = asdict(budget)
                    component_result["attempts"].append(attempt)
                    store.record_call(run_id, component.id, usage, attempt["seconds"], passed)
                    validation_blob = memory.put_blob("validation", json.dumps(validation))
                    memory.event(
                        "VALIDATION",
                        {
                            "component_id": component.id,
                            "passed": passed,
                            "summary": "passed" if passed else "component validation failed",
                            "blob": validation_blob,
                        },
                        repo=repo,
                        run_id=run_id,
                    )
                    if passed:
                        component_result["success"] = True
                        memory.event(
                            "COMPONENT_COMPLETED",
                            {"component_id": component.id},
                            repo=repo,
                            run_id=run_id,
                        )
                        component_seconds.append(time.perf_counter() - component_started)
                        remaining_after = len(plan.components) - component_index
                        eta_after = (
                            round(
                                sum(component_seconds)
                                / len(component_seconds)
                                * remaining_after
                            )
                            if remaining_after
                            else 0
                        )
                        progress(
                            {
                                "state": "updated",
                                "phase": "component",
                                "label": f"Component {component.id} passed validation",
                                "run_id": run_id,
                                "component_id": component.id,
                                "progress": component_index,
                                "total": len(plan.components),
                                "eta_seconds": eta_after,
                            }
                        )
                        state_row = store.connection.execute(
                            "SELECT state_json FROM task_state WHERE run_id=?", (run_id,)
                        ).fetchone()
                        checkpoint_id = workspace.checkpoint(
                            component.id,
                            json.loads(state_row["state_json"]) if state_row else {},
                            report | {"components": [*report["components"], component_result]},
                            assembled,
                        )
                        component_result["checkpoint_id"] = checkpoint_id
                        break
                    feedback = (
                        "Repair only the failing behavior.\n"
                        + "\n".join(
                            item["output"] for item in validation if item["exit_code"] != 0
                        )[-6000:]
                    )
                    category = classify_failure(feedback)
                    store.record_failure(
                        run_id,
                        component.id,
                        signature(category, feedback),
                        category,
                        {"attempt": number, "validation": validation},
                    )
                    number += 1
                report["components"].append(component_result)
                if not component_result["success"]:
                    break
            else:
                if store.cancelled(run_id):
                    raise RuntimeError("run cancelled")
                store.event(run_id, "INTEGRATING", {})
                progress(
                    {
                        "state": "updated",
                        "phase": "integration",
                        "label": "Running integration validation",
                        "run_id": run_id,
                        "progress": len(plan.components),
                        "total": len(plan.components),
                        "eta_seconds": None,
                    }
                )
                report["success"], report["integration_validation"] = _validation(
                    work, plan.integration_validation, python=project_python
                )
                memory.event(
                    "INTEGRATION_VALIDATED",
                    {"passed": report["success"]},
                    repo=repo,
                    run_id=run_id,
                )
            report["diff"] = _diff(repo, work, assembled)
            if report["success"] and apply:
                workspace.assert_source_fresh()
                memory.event(
                    "APPLY_STARTED",
                    {"paths": list(assembled)},
                    repo=repo,
                    run_id=run_id,
                )
                for relative in assembled:
                    if _digest(safe_path(repo, relative)) != hashes[relative]:
                        raise RuntimeError(f"concurrent change detected: {relative}")
                for relative in assembled:
                    source, destination = safe_path(work, relative), safe_path(repo, relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_name(f".{destination.name}.fresnel-tmp")
                    temporary.write_bytes(source.read_bytes())
                    temporary.replace(destination)
                report["applied"] = True
                memory.event(
                    "APPLY_COMPLETED",
                    {"paths": list(assembled)},
                    repo=repo,
                    run_id=run_id,
                )
        report["metrics"] = _metrics(report, config)
        status = (
            "READY_TO_APPLY"
            if report["success"] and not apply
            else "APPLIED"
            if report["success"] and apply
            else "COMPONENT_FAILED"
        )
        if report["notifications"]:
            status = "AWAITING_APPROVAL"
        report["status"] = status
        event_kind = (
            "INTERRUPTED"
            if status == "AWAITING_APPROVAL"
            else "RUN_COMPLETED"
            if report["success"]
            else "RUN_FAILED"
        )
        memory.event(
            event_kind,
            {"status": status, "summary": status.lower().replace("_", " ")},
            repo=repo,
            run_id=run_id,
        )
        workspace.mark(status)
        progress(
            {
                "state": "completed" if report["success"] else "failed",
                "phase": "complete",
                "label": "Fresnel run passed" if report["success"] else "Fresnel run failed",
                "run_id": run_id,
                "progress": sum(component["success"] for component in report["components"]),
                "total": len(plan.components),
                "eta_seconds": 0,
                "seconds": round(time.perf_counter() - run_started, 3),
                "error": "" if report["success"] else status,
            }
        )
        store.finish(run_id, status, report)
        return report
    except KeyboardInterrupt:
        report["status"] = "INTERRUPTED"
        report["success"] = False
        memory.event(
            "INTERRUPTED",
            {"status": "INTERRUPTED", "summary": "interrupted by user; safe to resume"},
            repo=repo,
            run_id=run_id,
        )
        workspace.mark("INTERRUPTED")
        store.finish(run_id, "INTERRUPTED", report)
        raise
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["metrics"] = _metrics(report, config)
        report["status"] = "CANCELLED" if str(exc) == "run cancelled" else "FAILED"
        memory.event(
            "RUN_FAILED",
            {"status": report["status"], "summary": report["error"]},
            repo=repo,
            run_id=run_id,
        )
        progress(
            {
                "state": "failed",
                "phase": "complete",
                "label": "Fresnel run failed",
                "run_id": run_id,
                "progress": len(report["components"]),
                "total": len(plan.components),
                "eta_seconds": 0,
                "seconds": round(time.perf_counter() - run_started, 3),
                "error": report["error"],
            }
        )
        workspace.mark(report["status"])
        store.finish(run_id, report["status"], report)
        return report
