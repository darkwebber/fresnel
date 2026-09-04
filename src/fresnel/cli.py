"""Fresnel command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .benchmark import calibrate
from .chat import complete
from .config import config_path, environment_key, keychain_set, load_config, save_config
from .engine import plan_request, run
from .integrations import install as install_integration
from .integrations import uninstall as uninstall_integration
from .learning import propose
from .mcp_server import serve as serve_mcp
from .onboarding import run_onboarding
from .progress import BenchmarkProgress
from .protocol import parse_plan
from .release import homebrew_formula
from .router import shadow_route
from .sampling import DEFAULT_CANDIDATES, tune
from .setup import doctor, guided_setup, server_command, uninstall_setup
from .store import Store


def emit(value, *, compact: bool = False) -> None:
    print(
        json.dumps(value, separators=(",", ":") if compact else None, indent=None if compact else 2)
    )


def load_decisions(path: Path | None) -> dict[str, str]:
    if not path:
        path = decisions_path()
        if not path.exists():
            return {}
    raw = json.loads(path.read_text())
    return raw.get("decisions", raw)


def cmd_setup(args) -> int:
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    with BenchmarkProgress(enabled=interactive and not args.skip_benchmark) as progress:
        result = guided_setup(
            assume_yes=args.yes,
            dry_run=args.dry_run,
            skip_benchmark=args.skip_benchmark,
            quick_benchmark=args.quick,
            with_service=args.service,
            progress=progress,
        )
    if interactive and not args.yes and not args.dry_run and not args.no_onboard:
        result["onboarding"] = run_onboarding()
        return 0 if result["onboarding"]["completed"] else 1
    else:
        emit(result)
    return 0


def cmd_onboard(args) -> int:
    result = run_onboarding(
        product=args.product,
        project=args.project.resolve() if args.project else None,
        service=args.service,
        assume_yes=args.yes,
    )
    return 0 if result["completed"] else 1


def cmd_doctor(args) -> int:
    result = doctor()
    if args.fix and not result["healthy"]:
        result["repair"] = guided_setup(assume_yes=args.yes, skip_benchmark=True)
        result = {"before": result, "after": doctor()}
    emit(result)
    health = result.get("healthy", result.get("after", {}).get("healthy", False))
    return 0 if health else 1


def cmd_serve(_args) -> int:
    config = load_config()
    os.execvp(server_command(config)[0], server_command(config))
    return 0


def cmd_benchmark(args) -> int:
    config = load_config()
    endpoint = f"http://{config.host}:{config.port}/v1/chat/completions"
    interactive = sys.stderr.isatty() and not args.json
    with BenchmarkProgress(enabled=interactive) as progress:
        result = calibrate(endpoint, quick=args.quick, progress=progress)
    config.profiles = result["profiles"]
    config.profile = result["selected_profile"]
    save_config(config)
    store = Store()
    store.record_benchmark(result["hardware"], result["results"], result["selected_profile"])
    store.connection.close()
    if args.json or not sys.stdout.isatty():
        emit(result)
    else:
        selected = result["profiles"][result["selected_profile"]]
        print(f"Saved profile: {result['selected_profile']}")
        print(
            f"Limits: {selected['context_window']:,} context · "
            f"{selected['max_output_tokens']:,} output"
        )
        print("Inspect anytime with `fresnel doctor --json`.")
    return 0


def _sampling_value(value, fallback):
    return fallback if value is None else value


def cmd_ask(args) -> int:
    question = " ".join(args.question).strip()
    if not question:
        question = sys.stdin.read().strip() if not sys.stdin.isatty() else input("Ask Spark: ").strip()
    if not question:
        raise ValueError("question cannot be empty")
    config = load_config()
    profile = config.selected_profile
    temperature = _sampling_value(args.temperature, profile.temperature)
    top_p = _sampling_value(args.top_p, profile.top_p)
    top_k = _sampling_value(args.top_k, profile.top_k)
    min_p = _sampling_value(args.min_p, profile.min_p)
    max_tokens = args.max_tokens or min(2048, profile.max_output_tokens)
    _validate_sampling(temperature, top_p, top_k, min_p)
    if not 1 <= max_tokens <= profile.max_output_tokens:
        raise ValueError(
            f"max_tokens must be between 1 and the active profile limit "
            f"({profile.max_output_tokens})"
        )
    endpoint = f"http://{config.host}:{config.port}/v1/chat/completions"
    with BenchmarkProgress(enabled=sys.stderr.isatty() and not args.json) as progress:
        progress({"state": "started", "label": "Spark is thinking"})
        try:
            result = complete(
                endpoint,
                question,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                min_p=min_p,
                system=args.system,
            )
        except Exception as exc:
            progress(
                {
                    "state": "failed",
                    "label": "Spark is thinking",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise
        progress(
            {
                "state": "completed",
                "label": "Spark answered",
                "seconds": result["seconds"],
                "cached_tokens": result["usage"]
                .get("prompt_tokens_details", {})
                .get("cached_tokens", 0),
            }
        )
    if args.json:
        emit({**result, "sampling": {"temperature": temperature, "top_p": top_p, "top_k": top_k, "min_p": min_p}})
    else:
        print(result["content"].rstrip())
    return 0


def cmd_tune(args) -> int:
    config = load_config()
    endpoint = f"http://{config.host}:{config.port}/v1/chat/completions"
    candidates = tuple(args.candidate) if args.candidate else DEFAULT_CANDIDATES
    if not candidates or any(value < 0 or value > 2 for value in candidates):
        raise ValueError("temperature candidates must be between 0 and 2")
    with BenchmarkProgress(enabled=sys.stderr.isatty() and not args.json) as progress:
        result = tune(endpoint, candidates=candidates, progress=progress)
    values = config.profiles.setdefault(config.profile, asdict(config.selected_profile))
    values["temperature"] = result["selected_temperature"]
    save_config(config)
    if args.json or not sys.stdout.isatty():
        emit(result)
    else:
        print(f"Selected temperature: {result['selected_temperature']:g}")
        for candidate in result["results"]:
            print(
                f"  {candidate['temperature']:g}: {candidate['score']}/{len(candidate['tasks'])} "
                f"checks · {candidate['seconds']}s"
            )
        print(f"Saved to the {config.profile} profile.")
    return 0


def coordinator_settings(args) -> tuple[str, str, str | None]:
    endpoint = args.coordinator_endpoint or os.environ.get("COORDINATOR_ENDPOINT")
    model = args.coordinator_model or os.environ.get("COORDINATOR_MODEL")
    if not endpoint or not model:
        raise ValueError("configure COORDINATOR_ENDPOINT and COORDINATOR_MODEL")
    return endpoint, model, environment_key("COORDINATOR_API_KEY", "coordinator-api-key")


def cmd_plan(args) -> int:
    endpoint, model, key = coordinator_settings(args)
    plan, calls = plan_request(args.request, args.repo.resolve(), endpoint, model, key)
    result = {"plan": asdict(plan), "coordinator_calls": calls}
    if args.output:
        args.output.write_text(json.dumps(result["plan"], indent=2) + "\n")
    emit(result)
    return 0


def cmd_run(args) -> int:
    coordinator_calls = []
    if args.plan:
        plan = parse_plan(json.loads(args.plan.read_text()))
        request = args.request or plan.objective
    else:
        endpoint, model, key = coordinator_settings(args)
        plan, coordinator_calls = plan_request(
            args.request, args.repo.resolve(), endpoint, model, key
        )
        request = args.request
    result = run(
        args.repo,
        plan,
        load_config(),
        request=request,
        apply=args.apply,
        decisions=load_decisions(args.approval_decisions),
        coordinator_calls=coordinator_calls,
    )
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    diff = result.get("diff", "")
    diff_limit = 20_000
    emit(
        {
            "protocol_version": result["protocol_version"],
            "run_id": result["run_id"],
            "status": result.get("status"),
            "success": result["success"],
            "applied": result["applied"],
            "metrics": result.get("metrics"),
            "notifications": result.get("notifications"),
            "failed_components": [
                component["id"] for component in result["components"] if not component["success"]
            ],
            "integration_validation": result.get("integration_validation"),
            "diff": diff if len(diff) <= diff_limit else diff[:diff_limit] + "\n[diff truncated]",
            "diff_truncated": len(diff) > diff_limit,
            "full_report": str(args.output.resolve())
            if args.output
            else "stored in Fresnel SQLite",
        }
    )
    if result["notifications"]:
        return 2
    return 0 if result["success"] else 1


def cmd_status(args) -> int:
    emit({"runs": Store().recent_runs(args.limit)})
    return 0


def decisions_path() -> Path:
    return config_path().with_name("approvals.json")


def cmd_approve(args) -> int:
    path = decisions_path()
    raw = json.loads(path.read_text()) if path.exists() else {"decisions": {}}
    raw["decisions"][args.request_id] = args.decision
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2) + "\n")
    emit({"saved": str(path), "request_id": args.request_id, "decision": args.decision})
    return 0


def cmd_review(args) -> int:
    report = json.loads(args.path.read_text())
    emit(
        {
            "run_id": report.get("run_id"),
            "success": report.get("success"),
            "applied": report.get("applied"),
            "metrics": report.get("metrics"),
            "notifications": report.get("notifications"),
            "review_checklist": report.get("plan", {}).get("review_checklist"),
            "diff": report.get("diff"),
        }
    )
    return 0


def cmd_integrations(args) -> int:
    project = args.project.resolve() if args.project else None
    if args.operation == "install":
        result = install_integration(args.product, project, dry_run=args.dry_run)
    else:
        result = uninstall_integration(args.product, project, dry_run=args.dry_run)
    emit(
        {
            "operation": args.operation,
            "product": args.product,
            "changes": result,
            "dry_run": args.dry_run,
        }
    )
    return 0


def cmd_key(args) -> int:
    keychain_set(args.account, args.value)
    emit({"stored": args.account, "service": "fresnel"})
    return 0


def cmd_config(args) -> int:
    config = load_config()
    if args.operation == "profile":
        if args.value not in config.profiles:
            raise ValueError(
                f"unknown profile: {args.value}; choose from {', '.join(config.profiles)}"
            )
        config.profile = args.value
    elif args.operation == "pricing":
        config.coordinator_input_cost_per_million = args.input
        config.coordinator_output_cost_per_million = args.output
    elif args.operation == "sampling":
        current = config.selected_profile
        temperature = _sampling_value(args.temperature, current.temperature)
        top_p = _sampling_value(args.top_p, current.top_p)
        top_k = _sampling_value(args.top_k, current.top_k)
        min_p = _sampling_value(args.min_p, current.min_p)
        _validate_sampling(temperature, top_p, top_k, min_p)
        values = config.profiles.setdefault(config.profile, asdict(current))
        values.update(
            {"temperature": temperature, "top_p": top_p, "top_k": top_k, "min_p": min_p}
        )
    save_config(config)
    emit({"config": asdict(config)})
    return 0


def _validate_sampling(temperature: float, top_p: float, top_k: int, min_p: float) -> None:
    if not 0 <= temperature <= 2:
        raise ValueError("temperature must be between 0 and 2")
    if not 0 < top_p <= 1:
        raise ValueError("top_p must be greater than 0 and at most 1")
    if top_k < 0:
        raise ValueError("top_k must be non-negative")
    if not 0 <= min_p <= 1:
        raise ValueError("min_p must be between 0 and 1")


def cmd_learn(_args) -> int:
    store = Store()
    emit({"mode": "proposal_only", "proposals": propose(store), "existing": store.improvements()})
    return 0


def cmd_route(args) -> int:
    emit(shadow_route({"targets": args.target, "api_uncertainty": args.api_uncertainty}))
    return 0


def cmd_formula(args) -> int:
    formula = homebrew_formula(args.version, args.url, args.sha256.lower(), homepage=args.homepage)
    if args.output:
        args.output.write_text(formula)
    else:
        print(formula)
    return 0


def cmd_uninstall(args) -> int:
    emit(uninstall_setup(purge_state=args.purge_state, dry_run=args.dry_run))
    return 0


def cmd_migrate(args) -> int:
    store = Store()
    imported = []
    paths = sorted(args.path.glob("*.json")) if args.path.is_dir() else [args.path]
    for path in paths:
        raw = json.loads(path.read_text())
        if not {"model", "mode", "results"}.issubset(raw):
            continue
        identifier = store.record_benchmark(
            {"source": "legacy_harness_eval", "model": raw["model"]},
            raw,
            f"legacy-{raw['mode']}",
        )
        imported.append({"id": identifier, "path": str(path), "mode": raw["mode"]})
    store.close()
    emit({"imported": imported, "skipped": len(paths) - len(imported)})
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="fresnel", description="Fresnel local-agent harness")
    root.add_argument("--version", action="version", version=f"Fresnel {__version__}")
    commands = root.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="guided Apple Silicon setup")
    setup.add_argument("--yes", action="store_true")
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument("--skip-benchmark", action="store_true")
    setup.add_argument("--quick", action="store_true")
    setup.add_argument("--service", action="store_true")
    setup.add_argument("--no-onboard", action="store_true")
    setup.set_defaults(handler=cmd_setup)

    onboard = commands.add_parser("onboard", help="finish setup with an interactive walkthrough")
    onboard.add_argument("--product", choices=("codex", "cursor", "opencode", "generic", "skip"))
    onboard.add_argument("--project", type=Path)
    onboard.add_argument("--yes", action="store_true")
    service_choice = onboard.add_mutually_exclusive_group()
    service_choice.add_argument("--service", dest="service", action="store_true")
    service_choice.add_argument("--no-service", dest="service", action="store_false")
    onboard.set_defaults(handler=cmd_onboard, service=None)

    doctor_parser = commands.add_parser("doctor", help="diagnose installation")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument("--fix", action="store_true")
    doctor_parser.add_argument("--yes", action="store_true")
    doctor_parser.set_defaults(handler=cmd_doctor)
    commands.add_parser("serve", help="run the local Spark server").set_defaults(handler=cmd_serve)

    benchmark = commands.add_parser("benchmark", help="calibrate this Mac")
    benchmark.add_argument("--quick", action="store_true")
    benchmark.add_argument("--json", action="store_true")
    benchmark.set_defaults(handler=cmd_benchmark)

    ask = commands.add_parser("ask", help="ask the local Spark model a one-off question")
    ask.add_argument("question", nargs="*")
    ask.add_argument("--system", default="You are a concise, accurate local coding assistant.")
    ask.add_argument("--max-tokens", type=int)
    ask.add_argument("--temperature", type=float)
    ask.add_argument("--top-p", type=float)
    ask.add_argument("--top-k", type=int)
    ask.add_argument("--min-p", type=float)
    ask.add_argument("--json", action="store_true")
    ask.set_defaults(handler=cmd_ask)

    tune_parser = commands.add_parser("tune", help="auto-tune sampling on local behavior checks")
    tune_parser.add_argument("--candidate", type=float, action="append")
    tune_parser.add_argument("--json", action="store_true")
    tune_parser.set_defaults(handler=cmd_tune)

    plan = commands.add_parser("plan", help="compile a request into a Fresnel plan")
    plan.add_argument("--repo", type=Path, required=True)
    plan.add_argument("--request", required=True)
    plan.add_argument("--coordinator-endpoint")
    plan.add_argument("--coordinator-model")
    plan.add_argument("--output", type=Path)
    plan.set_defaults(handler=cmd_plan)

    run_parser = commands.add_parser("run", help="plan/delegate/validate in a disposable workspace")
    run_parser.add_argument("--repo", type=Path, required=True)
    source = run_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path)
    source.add_argument("--request")
    run_parser.add_argument("--coordinator-endpoint")
    run_parser.add_argument("--coordinator-model")
    run_parser.add_argument("--approval-decisions", type=Path)
    run_parser.add_argument("--apply", action="store_true")
    run_parser.add_argument("--output", type=Path)
    run_parser.set_defaults(handler=cmd_run)

    status = commands.add_parser("status", help="show recent runs")
    status.add_argument("--limit", type=int, default=20)
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    approval = commands.add_parser("approve", help="record an approval decision")
    approval.add_argument("request_id")
    approval.add_argument("decision", choices=("approve", "deny"))
    approval.set_defaults(handler=cmd_approve)

    review = commands.add_parser("review", help="render a compact review packet")
    review.add_argument("path", type=Path)
    review.set_defaults(handler=cmd_review)

    integrations = commands.add_parser("integrations", help="install thin orchestrator adapters")
    integrations.add_argument("operation", choices=("install", "uninstall"))
    integrations.add_argument("product", choices=("codex", "cursor", "opencode", "generic"))
    integrations.add_argument("--project", type=Path)
    integrations.add_argument("--dry-run", action="store_true")
    integrations.set_defaults(handler=cmd_integrations)

    key = commands.add_parser("key", help="store a credential in macOS Keychain")
    key.add_argument("account", choices=("exa-api-key", "coordinator-api-key"))
    key.add_argument("value")
    key.set_defaults(handler=cmd_key)

    config = commands.add_parser("config", help="select profiles and coordinator pricing")
    config_sub = config.add_subparsers(dest="operation", required=True)
    profile = config_sub.add_parser("profile", help="select eco, balanced, or maximum")
    profile.add_argument("value")
    profile.set_defaults(handler=cmd_config)
    pricing = config_sub.add_parser("pricing", help="set coordinator USD cost per million tokens")
    pricing.add_argument("--input", type=float, required=True)
    pricing.add_argument("--output", type=float, required=True)
    pricing.set_defaults(handler=cmd_config)
    sampling = config_sub.add_parser("sampling", help="tune local worker sampling")
    sampling.add_argument("--temperature", type=float)
    sampling.add_argument("--top-p", type=float)
    sampling.add_argument("--top-k", type=int)
    sampling.add_argument("--min-p", type=float)
    sampling.set_defaults(handler=cmd_config)

    commands.add_parser("learn", help="propose evidence-backed prompt improvements").set_defaults(
        handler=cmd_learn
    )
    route = commands.add_parser("route", help="show the shadow routing decision")
    route.add_argument("--target", action="append", default=[])
    route.add_argument("--api-uncertainty", action="store_true")
    route.set_defaults(handler=cmd_route)
    commands.add_parser("mcp", help="serve MCP over stdio").set_defaults(
        handler=lambda _args: serve_mcp() or 0
    )

    formula = commands.add_parser("formula", help="generate a Homebrew release formula")
    formula.add_argument("--version", required=True)
    formula.add_argument("--url", required=True)
    formula.add_argument("--sha256", required=True)
    formula.add_argument("--homepage", default="https://github.com/fresnel-ai/fresnel")
    formula.add_argument("--output", type=Path)
    formula.set_defaults(handler=cmd_formula)
    uninstall = commands.add_parser("uninstall", help="remove service and optionally Fresnel state")
    uninstall.add_argument("--purge-state", action="store_true")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.set_defaults(handler=cmd_uninstall)
    migrate = commands.add_parser("migrate-results", help="import legacy benchmark JSON evidence")
    migrate.add_argument("path", type=Path)
    migrate.set_defaults(handler=cmd_migrate)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        code = args.handler(args)
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:
        emit({"error": f"{type(exc).__name__}: {exc}"})
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
