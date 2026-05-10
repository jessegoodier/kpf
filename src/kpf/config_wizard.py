"""Interactive configuration wizard for kpf."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()


@dataclass
class _Option:
    key: str
    kind: str  # "bool" | "int" | "str"
    default: Any
    group: str
    description: str


_OPTIONS = [
    _Option(
        key="autoSelectFreePort",
        kind="bool",
        default=True,
        group="Port Handling",
        description=(
            "When the requested local port is already in use, automatically try the next "
            "available port (9091, 9092, ...) rather than failing immediately."
        ),
    ),
    _Option(
        key="alwaysListenAll",
        kind="bool",
        default=False,
        group="Port Handling",
        description=(
            "Always bind to 0.0.0.0 (all interfaces) instead of localhost. "
            "Equivalent to passing --listen-all / -z on every invocation."
        ),
    ),
    _Option(
        key="showDirectCommand",
        kind="bool",
        default=True,
        group="Display",
        description=(
            "After connecting to a service, print the exact kpf command so you can "
            "run it directly next time without going through the TUI."
        ),
    ),
    _Option(
        key="showDirectCommandIncludeContext",
        kind="bool",
        default=True,
        group="Display",
        description=(
            "Include --context in the printed direct command. Useful when you work with "
            "multiple clusters and want the saved command to be cluster-specific."
        ),
    ),
    _Option(
        key="showDirectCommandIncludeKubeconfig",
        kind="bool",
        default=True,
        group="Display",
        description=(
            "Include --kubeconfig in the printed direct command when a non-default kubeconfig "
            "is in use. Useful when you work with custom or per-project kubeconfig files."
        ),
    ),
    _Option(
        key="directCommandMultiLine",
        kind="bool",
        default=True,
        group="Display",
        description="Break the printed direct command across multiple lines for readability.",
    ),
    _Option(
        key="autoReconnect",
        kind="bool",
        default=True,
        group="Reconnection",
        description=(
            "Automatically restart the port-forward when the connection drops. "
            "Disabling this causes kpf to exit on any connection failure."
        ),
    ),
    _Option(
        key="reconnectAttempts",
        kind="int",
        default=30,
        group="Reconnection",
        description=(
            "Maximum consecutive reconnection attempts before kpf gives up and exits. "
            "Set to 0 for unlimited retries."
        ),
    ),
    _Option(
        key="reconnectDelaySeconds",
        kind="int",
        default=5,
        group="Reconnection",
        description="Seconds to wait between reconnection attempts.",
    ),
    _Option(
        key="restartThrottleSeconds",
        kind="int",
        default=5,
        group="Reconnection",
        description=(
            "Minimum seconds between restarts. Prevents rapid restart loops "
            "when endpoints are continuously changing."
        ),
    ),
    _Option(
        key="networkWatchdogEnabled",
        kind="bool",
        default=True,
        group="Network Watchdog",
        description=(
            "Run a background thread that probes K8s API connectivity. Detects zombie "
            "tunnels that appear open but are dead — most common after laptop sleep/wake."
        ),
    ),
    _Option(
        key="networkWatchdogInterval",
        kind="int",
        default=5,
        group="Network Watchdog",
        description="Seconds between watchdog connectivity probes.",
    ),
    _Option(
        key="networkWatchdogFailureThreshold",
        kind="int",
        default=2,
        group="Network Watchdog",
        description=(
            "Consecutive probe failures required before the watchdog triggers "
            "a port-forward restart."
        ),
    ),
    _Option(
        key="saveCommandHistory",
        kind="bool",
        default=False,
        group="History",
        description=(
            "Write each session's service, namespace, ports, and cluster context to a local "
            "JSON file. Never sent anywhere. Required to enable the h key history menu "
            "in the interactive TUI."
        ),
    ),
    _Option(
        key="saveHistoryLocation",
        kind="str",
        default="~/.config/kpf/command-history",
        group="History",
        description=(
            "Directory where per-session JSON files are stored. Use ~ for your home directory."
        ),
    ),
]

_DEFAULTS = {o.key: o.default for o in _OPTIONS}


def _fmt_value(value: Any) -> str:
    """Human-readable value string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _prompt_value(opt: _Option, current: Any) -> Any:
    """Display one option and return the user's chosen value."""
    console.print()

    header = Text()
    header.append(f"  {opt.key}", style="bold bright_white")
    header.append(f"   default: {_fmt_value(opt.default)}", style="magenta")
    console.print(header)
    console.print(f"  [yellow3]{opt.description}[/yellow3]")
    console.print()

    if opt.kind == "bool":
        return Confirm.ask("  Enable", default=bool(current))
    elif opt.kind == "int":
        return IntPrompt.ask("  Value", default=int(current))
    else:
        return Prompt.ask("  Value", default=str(current))


def run_config_wizard(config) -> None:
    """Walk the user through every config option and write the result to disk.

    Only values that differ from their defaults are written, keeping the
    config file minimal so future kpf defaults apply automatically.
    """
    config_path: Path = config.get_config_path()

    # Read the existing raw file so we show the user's saved values, not
    # the expanded runtime values stored in config.config.
    existing_raw: dict = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                existing_raw = json.load(f)
        except Exception:
            pass

    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold bright_cyan]kpf Configuration Wizard[/bold bright_cyan]\n\n"
                "Press [bold]Enter[/bold] at each prompt to keep the shown default.\n"
                "Only values that differ from defaults are written to the config file.\n"
                f"[magenta]Config path:[/magenta] [bold bright_white]{config_path}[bold bright_white]"
            ),
            box=box.ROUNDED,
            border_style="cyan",
            expand=False,
            padding=(0, 2),
        )
    )

    collected: dict = {}
    current_group = None
    total = len(_OPTIONS)

    try:
        for i, opt in enumerate(_OPTIONS, 1):
            if opt.group != current_group:
                current_group = opt.group
                console.print()
                console.print(Rule(f"[bold cyan]{opt.group}[/bold cyan]", style="cyan"))

            console.print(f"\n  {i} / {total}", end="")

            starting = existing_raw.get(opt.key, opt.default)
            collected[opt.key] = _prompt_value(opt, starting)

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Wizard cancelled — no changes saved.[/yellow]")
        return

    # Determine what actually differs from defaults
    changed = {k: v for k, v in collected.items() if v != _DEFAULTS.get(k)}

    console.print()
    console.print(Rule("[bold cyan]Summary[/bold cyan]", style="cyan"))
    console.print()

    if changed:
        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold bright_white",
            padding=(0, 2),
        )
        table.add_column("Option", style="bold white", no_wrap=True)
        table.add_column("Value", style="green", no_wrap=True)
        table.add_column("Default", no_wrap=True)

        for opt in _OPTIONS:
            if opt.key in changed:
                table.add_row(
                    opt.key,
                    _fmt_value(changed[opt.key]),
                    _fmt_value(opt.default),
                )

        console.print(table)
    else:
        console.print("  All options kept at their defaults — config file will be empty.")

    console.print()

    try:
        if not Confirm.ask(f"  Save to [cyan]{config_path}[/cyan]", default=True):
            console.print("[yellow]Not saved.[/yellow]")
            return
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled — no changes saved.[/yellow]")
        return

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(changed, f, indent=2)
            f.write("\n")
        console.print(f"\n[green]Saved to {config_path}[/green]")
    except Exception as e:
        console.print(f"[red]Error saving config: {e}[/red]")
