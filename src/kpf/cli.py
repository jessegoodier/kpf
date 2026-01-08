#!/usr/bin/env python3

import argparse
import locale
import os
import platform
import subprocess
import sys
from typing import List, Optional

from rich.console import Console

from . import __version__
from .config import get_config
from .display import ServiceSelector
from .kubernetes import KubernetesClient
from .main import run_port_forward

# Initialize Rich console
console = Console()


def str_to_bool(value):
    """Convert string to boolean for CLI arguments."""
    if isinstance(value, bool):
        return value
    if value.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif value.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError(f"Boolean value expected, got: {value}")


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="kpf",
        description="A better Kubectl Port-Forward that automatically restarts port-forwards when endpoints change",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""

Example usage:
  kpf                                           # Interactive mode
  kpf svc/frontend 8080:8080 -n production      # Direct port-forward (maintain expected behavior)
  kpf -n production                             # Interactive selection in specific namespace
  kpf --all (or -A)                             # Show all services across all namespaces
  kpf --all-ports (or -l)                       # Show all services with their ports
  kpf --check -n production                     # Interactive selection with endpoint status
  kpf --prompt-namespace (or -pn)               # Interactive namespace selection
  kpf -0                                        # Listen on 0.0.0.0 (all interfaces)
        """,
    )

    parser.add_argument("--version", "-v", action="version", version=f"kpf {__version__}")

    parser.add_argument(
        "--namespace",
        "-n",
        type=str,
        help="Kubernetes namespace to use (default: current context namespace)",
    )

    parser.add_argument(
        "--prompt-namespace",
        "-pn",
        action="store_true",
        help="Interactively select a namespace before service selection",
    )

    parser.add_argument(
        "--all",
        "-A",
        action="store_true",
        help="Show all services across all namespaces in a sorted table",
    )

    parser.add_argument(
        "--all-ports",
        "-l",
        action="store_true",
        help="Include ports from pods, deployments, daemonsets, etc.",
    )

    parser.add_argument(
        "--check",
        "-c",
        action="store_true",
        help="Check and display endpoint status in service selection table",
    )

    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug output for troubleshooting",
    )

    parser.add_argument(
        "--debug-terminal",
        "-t",
        action="store_true",
        help="Enable debug output for troubleshooting display issues",
    )

    parser.add_argument(
        "--run-http-health-checks",
        action="store_true",
        help="Enable HTTP connectivity health checks (disabled by default)",
    )

    parser.add_argument(
        "-0",
        dest="address_zero",
        action="store_true",
        help="Listen on all interfaces (0.0.0.0) instead of localhost",
    )

    # Configuration override arguments
    config_group = parser.add_argument_group("configuration overrides")

    # Boolean flags with explicit values
    config_group.add_argument(
        "--auto-select-free-port",
        dest="auto_select_free_port",
        type=str_to_bool,
        default=None,
        metavar="BOOL",
        help="Automatically select next free port if requested port is busy (true/false, default: from config)",
    )

    config_group.add_argument(
        "--show-direct-command",
        dest="show_direct_command",
        type=str_to_bool,
        default=None,
        metavar="BOOL",
        help="Show the direct kpf command for future use (true/false, default: from config)",
    )

    config_group.add_argument(
        "--show-context",
        dest="show_context",
        type=str_to_bool,
        default=None,
        metavar="BOOL",
        help="Include --context in direct command output (true/false, default: from config)",
    )

    config_group.add_argument(
        "--multiline-command",
        dest="multiline_command",
        type=str_to_bool,
        default=None,
        metavar="BOOL",
        help="Format direct command across multiple lines (true/false, default: from config)",
    )

    config_group.add_argument(
        "--auto-reconnect",
        dest="auto_reconnect",
        type=str_to_bool,
        default=None,
        metavar="BOOL",
        help="Automatically reconnect when connection drops (true/false, default: from config)",
    )

    config_group.add_argument(
        "--capture-usage",
        dest="capture_usage",
        type=str_to_bool,
        default=None,
        metavar="BOOL",
        help="Log usage details to files for analytics (true/false, default: from config)",
    )

    # Integer/String arguments
    config_group.add_argument(
        "--reconnect-attempts",
        type=int,
        default=None,
        metavar="N",
        help="Number of reconnection attempts before giving up (default: 30)",
    )

    config_group.add_argument(
        "--reconnect-delay",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Delay in seconds between reconnection attempts (default: 5)",
    )

    config_group.add_argument(
        "--usage-folder",
        type=str,
        default=None,
        metavar="PATH",
        help="Folder to store usage detail logs (default: from config)",
    )

    # Positional arguments for legacy port-forward syntax
    parser.add_argument("args", nargs="*", help="kubectl port-forward arguments (legacy mode)")

    return parser


def merge_config_with_cli_args(config, args):
    """Merge CLI arguments with config, CLI args take precedence.

    Args:
        config: KpfConfig instance
        args: argparse.Namespace with CLI arguments

    Returns:
        dict: Merged configuration with CLI args overriding config file values
    """
    merged = config.config.copy()

    arg_mapping = {
        "auto_select_free_port": "autoSelectFreePort",
        "show_direct_command": "showDirectCommand",
        "show_context": "showDirectCommandIncludeContext",
        "multiline_command": "directCommandMultiLine",
        "auto_reconnect": "autoReconnect",
        "reconnect_attempts": "reconnectAttempts",
        "reconnect_delay": "reconnectDelaySeconds",
        "capture_usage": "captureUsageDetails",
        "usage_folder": "usageDetailFolder",
    }

    for arg_name, config_key in arg_mapping.items():
        arg_value = getattr(args, arg_name, None)
        if arg_value is not None:  # Only override if explicitly provided
            merged[config_key] = arg_value

    return merged


def handle_prompt_mode(
    namespace: Optional[str] = None,
    show_all: bool = False,
    show_all_ports: bool = False,
    check_endpoints: bool = False,
) -> List[str]:
    """Handle interactive service selection."""
    k8s_client = KubernetesClient()
    selector = ServiceSelector(k8s_client)

    if show_all:
        return selector.select_service_all_namespaces(show_all_ports, check_endpoints)
    else:
        return selector.select_service_in_namespace(namespace, show_all_ports, check_endpoints)


def check_kubectl():
    """Check if kubectl is available."""
    try:
        subprocess.run(["kubectl", "version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("kubectl is not available or not configured properly")


def _debug_display_terminal_capabilities():
    """Display terminal capabilities and environment information for debugging."""
    console.print("\n[bold cyan]═══ Terminal Environment Debug Information ═══[/bold cyan]")

    # Basic runtime info
    console.print(f"[dim]Python:[/dim] [green]{sys.version.split()[0]}[/green]")
    console.print(f"[dim]Platform:[/dim] [green]{platform.platform()}[/green]")

    # Terminal type
    term = os.environ.get("TERM", "unknown")
    console.print(f"[dim]TERM:[/dim] [green]{term}[/green]")

    # Terminal dimensions
    try:
        size = os.get_terminal_size()
        console.print(f"[dim]Columns:[/dim] [green]{size.columns}[/green]")
        console.print(f"[dim]Lines:[/dim] [green]{size.lines}[/green]")
    except OSError:
        console.print(
            "[dim]Columns:[/dim] [yellow]Unable to detect (non-interactive session)[/yellow]"
        )
        console.print(
            "[dim]Lines:[/dim] [yellow]Unable to detect (non-interactive session)[/yellow]"
        )

    # Rich/stream/TTY status
    try:
        console_size = console.size
        console.print(
            f"[dim]Rich Console Size:[/dim] [green]{console_size.width}×{console_size.height}[/green]"
        )
    except Exception:
        pass
    console.print(
        f"[dim]stdin isatty:[/dim] [green]{getattr(sys.stdin, 'isatty', lambda: False)()}[/green]"
    )
    console.print(
        f"[dim]stdout isatty:[/dim] [green]{getattr(sys.stdout, 'isatty', lambda: False)()}[/green]"
    )
    console.print(
        f"[dim]stderr isatty:[/dim] [green]{getattr(sys.stderr, 'isatty', lambda: False)()}[/green]"
    )

    # Encoding and locale
    console.print(
        f"[dim]stdout encoding:[/dim] [green]{getattr(sys.stdout, 'encoding', None) or 'None'}[/green]"
    )
    console.print(
        f"[dim]preferred encoding:[/dim] [green]{locale.getpreferredencoding(False)}[/green]"
    )
    current_locale = locale.getlocale()
    console.print(f"[dim]locale:[/dim] [green]{current_locale}[/green]")
    py_io_encoding = os.environ.get("PYTHONIOENCODING")
    if py_io_encoding:
        console.print(f"[dim]PYTHONIOENCODING:[/dim] [green]{py_io_encoding}[/green]")

    # Color support detection
    colorterm = os.environ.get("COLORTERM", "")
    if colorterm:
        console.print(f"[dim]COLORTERM:[/dim] [green]{colorterm}[/green]")

    # Rich console capabilities
    console.print(f"[dim]Rich Color System:[/dim] [green]{console.color_system or 'None'}[/green]")
    console.print(f"[dim]Rich Legacy Windows:[/dim] [green]{console.legacy_windows}[/green]")
    console.print(f"[dim]Rich Force Terminal:[/dim] [green]{console._force_terminal}[/green]")

    # Terminal program (iTerm2, tmux, SSH, etc.)
    term_program = os.environ.get("TERM_PROGRAM")
    term_program_version = os.environ.get("TERM_PROGRAM_VERSION")
    iterm_profile = os.environ.get("ITERM_PROFILE")
    iterm_session = os.environ.get("ITERM_SESSION_ID")
    if term_program:
        console.print(f"[dim]TERM_PROGRAM:[/dim] [green]{term_program}[/green]")
    if term_program_version:
        console.print(f"[dim]TERM_PROGRAM_VERSION:[/dim] [green]{term_program_version}[/green]")
    if iterm_profile:
        console.print(f"[dim]ITERM_PROFILE:[/dim] [green]{iterm_profile}[/green]")
    if iterm_session:
        console.print(f"[dim]ITERM_SESSION_ID:[/dim] [green]{iterm_session}[/green]")
    if os.environ.get("TMUX"):
        console.print(f"[dim]TMUX:[/dim] [green]{os.environ.get('TMUX')}[/green]")
    if os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION"):
        console.print("[dim]SSH:[/dim] [green]yes[/green]")

    # Common env flags that affect color/unicode
    for var in (
        "NO_COLOR",
        "FORCE_COLOR",
        "KPF_TTY_COMPAT",
        "COLUMNS",
        "LINES",
        "LC_ALL",
        "LC_CTYPE",
        "LANG",
    ):
        value = os.environ.get(var)
        if value:
            console.print(f"[dim]{var}:[/dim] [green]{value}[/green]")

    # tput-based capabilities (colors)
    try:
        colors = subprocess.run(["tput", "colors"], capture_output=True, text=True, check=False)
        colors_value = colors.stdout.strip() or colors.stderr.strip()
        if colors_value:
            console.print(f"[dim]tput colors:[/dim] [green]{colors_value}[/green]")
    except Exception:
        pass

    # What box style will be used by our tables
    compat_mode = os.environ.get("KPF_TTY_COMPAT") != "0"
    console.print(
        f"[dim]KPF box style:[/dim] [green]{'SIMPLE' if compat_mode else 'ROUNDED'}[/green]"
    )

    # Optional wcwidth checks for characters we render (mostly simple ASCII now)
    try:
        from wcwidth import wcswidth  # type: ignore

        samples = {
            "pointer_simple": ">",
            "pointer_fancy": "➤",
            "check": "✓",
            "cross": "✗",
        }
        console.print("[dim]wcwidth (wcswidth) for sample glyphs:[/dim]")
        for name, ch in samples.items():
            width = wcswidth(ch)
            console.print(f"  [dim]{name}[/dim]: '{ch}' -> [green]{width}[/green]")
    except Exception:
        console.print("[dim]wcwidth:[/dim] [yellow]unavailable[/yellow]")

    console.print("[bold cyan]══════════════════════════════════════════════[/bold cyan]\n")


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args, unknown_args = parser.parse_known_args()
    if args.debug_terminal:
        print("Debug mode enabled")
        _debug_display_terminal_capabilities()

    # Load configuration and merge with CLI args
    config = get_config()
    merged_config = merge_config_with_cli_args(config, args)

    try:
        port_forward_args = None

        # Handle interactive namespace selection if requested
        if args.prompt_namespace:
            # We need a client to check namespaces
            # Reuse the client from handle_prompt_mode or create a new one?
            # Creating a new one here is cleaner for flow control
            k8s_client = KubernetesClient()
            selector = ServiceSelector(k8s_client)
            selected_ns = selector.select_namespace()
            if selected_ns:
                args.namespace = selected_ns
            else:
                # User cancelled namespace selection
                console.print("Namespace selection cancelled. Exiting.", style="dim")
                sys.exit(0)

        # Handle interactive modes
        if args.all or args.all_ports or args.check:
            port_forward_args = handle_prompt_mode(
                namespace=args.namespace,
                show_all=args.all,
                show_all_ports=args.all_ports,
                check_endpoints=args.check,
            )
            if not port_forward_args:
                console.print("No service selected. Exiting.", style="dim")
                sys.exit(0)

        # Handle legacy mode (direct kubectl port-forward arguments)
        elif args.args or unknown_args:
            # Combine explicit args and unknown kubectl arguments
            port_forward_args = args.args + unknown_args
            # Add namespace if specified and not already present
            if (
                args.namespace
                and "-n" not in port_forward_args
                and "--namespace" not in port_forward_args
            ):
                port_forward_args.extend(["-n", args.namespace])

        else:
            # Default to interactive mode if no arguments are provided
            port_forward_args = handle_prompt_mode(
                namespace=args.namespace,
                show_all=args.all,
                show_all_ports=args.all_ports,
                check_endpoints=args.check,
            )
            if not port_forward_args:
                console.print("No service selected. Exiting.", style="dim")
                sys.exit(0)

        # Apply the -0 flag if specified
        if args.address_zero and port_forward_args:
            # Check if --address is already specified to avoid duplicates/conflicts
            if "--address" not in port_forward_args:
                port_forward_args.extend(["--address", "0.0.0.0"])

        # Run the port-forward utility (should only reach here if port_forward_args is set)
        if port_forward_args:
            run_port_forward(
                port_forward_args,
                debug_mode=args.debug,
                config=merged_config,
                run_http_health_checks=args.run_http_health_checks,
            )

    except KeyboardInterrupt:
        console.print("\nOperation cancelled by user (Ctrl+C)", style="yellow")
        sys.exit(0)
    except Exception as e:
        console.print(f"Error: {e}", style="red")
        sys.exit(1)


if __name__ == "__main__":
    main()
