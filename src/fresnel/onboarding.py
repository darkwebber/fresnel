"""Dependency-free terminal onboarding for a newly configured Fresnel install."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from .config import load_config, save_config
from .integrations import install as install_integration
from .setup import doctor, install_service, server_healthy

PRODUCTS = (
    ("codex", "Codex", "global skill"),
    ("cursor", "Cursor", "project rule"),
    ("opencode", "OpenCode", "project agent"),
    ("generic", "Other", "portable FRESNEL.md"),
    ("skip", "Not now", "show manual commands"),
)


def _choice(
    prompt: str,
    options: tuple[tuple[str, str, str], ...],
    *,
    default: int,
    input_fn: Callable[[str], str],
    output: Callable[[str], None],
) -> str:
    output(prompt)
    for number, (_value, label, detail) in enumerate(options, 1):
        marker = "•" if number == default else " "
        output(f"  {marker} {number}. {label:<10} {detail}")
    while True:
        answer = input_fn(f"Choose [{default}]: ").strip()
        if not answer:
            return options[default - 1][0]
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        output(f"Enter a number from 1 to {len(options)}.")


def _yes_no(
    prompt: str, *, default: bool, input_fn: Callable[[str], str], output: Callable[[str], None]
) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input_fn(f"{prompt} [{suffix}] ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        output("Enter y or n.")


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def run_onboarding(
    *,
    product: str | None = None,
    project: Path | None = None,
    service: bool | None = None,
    assume_yes: bool = False,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
    color: bool | None = None,
) -> dict:
    """Guide a user from installed bits to an enabled orchestrator workflow."""
    color = sys.stdout.isatty() if color is None else color
    status = doctor()
    config = load_config()

    output("")
    output(_paint("╭──────────────────────────────────────────────────────╮", "36", color))
    output(_paint("│  FRESNEL  ·  turn your local model into a teammate   │", "1;36", color))
    output(_paint("╰──────────────────────────────────────────────────────╯", "36", color))
    output("")
    chip = status["hardware"].get("chip", "Apple Silicon")
    memory_bytes = status["hardware"].get("memory_bytes", 0)
    memory = round(memory_bytes / 1024**3) if memory_bytes else "?"
    profile = config.selected_profile
    output(f"  {_paint('✓', '32', color)} Hardware   {chip} · {memory} GB unified memory")
    output(f"  {_paint('✓', '32', color)} Model      Spark-X2.5 4B MLX 8-bit")
    output(
        f"  {_paint('✓', '32', color)} Profile    {config.profile} · "
        f"{profile.context_window:,} context · {profile.max_output_tokens:,} output · "
        f"temperature {profile.temperature:g}"
    )
    if status["problems"]:
        for problem in status["problems"]:
            output(f"  {_paint('!', '31', color)} {problem}")
        output("\nRun `fresnel doctor --fix --yes`, then return with `fresnel onboard`.")
        return {"completed": False, "problems": status["problems"]}

    output("\nFresnel needs two final choices: how the worker runs and which")
    output("coding orchestrator should receive the Fresnel delegation contract.\n")

    if service is None:
        service = True if assume_yes else _yes_no(
            "Start the local worker automatically when you sign in?",
            default=True,
            input_fn=input_fn,
            output=output,
        )
    service_path = None
    if service and not config.start_at_login:
        service_path = install_service(config)
        config.start_at_login = True
        save_config(config)
    elif not service and config.start_at_login:
        output("  Existing login service kept enabled. Use `fresnel uninstall` to remove it.")

    valid_products = {item[0] for item in PRODUCTS}
    if product is None:
        product = "codex" if assume_yes else _choice(
            "Which orchestrator do you use most?",
            PRODUCTS,
            default=1,
            input_fn=input_fn,
            output=output,
        )
    if product not in valid_products:
        raise ValueError(f"unknown orchestrator: {product}")

    changes = []
    if product != "skip":
        if product != "codex" and project is None:
            supplied = "" if assume_yes else input_fn(f"Project directory [{Path.cwd()}]: ").strip()
            project = Path(supplied).expanduser() if supplied else Path.cwd()
        changes = install_integration(product, project)

    live = server_healthy(config.host, config.port)
    output("\n" + _paint("Ready.", "1;32", color))
    output("  The orchestrator plans and reviews. Spark implements bounded components.")
    if service:
        output("  Worker: starts at login" + (" and is responding now." if live else "."))
    else:
        output("  Worker: run `fresnel serve` in a separate terminal before delegating.")
    if product == "codex":
        output("  Codex: restart Codex once so it discovers the Fresnel skill.")
    elif product != "skip":
        output(f"  Integration: {product} configured for {project}.")
    else:
        output("  Integration: skipped; run `fresnel integrations install --help` later.")
    output("\nTry this in your orchestrator:")
    output(_paint('  “Use Fresnel to implement a small, well-tested change in this project.”', "36", color))
    output("\nUseful checks:  fresnel doctor --json   ·   fresnel status")

    return {
        "completed": True,
        "product": product,
        "project": str(project.resolve()) if project else None,
        "service": str(service_path) if service_path else ("enabled" if config.start_at_login else None),
        "server_healthy": live,
        "integration_changes": changes,
    }
