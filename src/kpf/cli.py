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
from .display import ServiceSelector
from .kubernetes import KubernetesClient
from .main import run_port_forward

# Initialize Rich console
console = Console()


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="kpf",
        description="A better Kubectl Port-Forward that automatically restarts port-forwards when endpoints change",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
There is no default command. You must specify one of the arguments below.
You could alias kpf to -p for interactive mode if you prefer.
Example of this in your ~/.zshrc:
alias kpf='uvx kpf -p'

Example usage:
  kpf svc/frontend 8080:8080 -n production      # Direct port-forward (backwards compatible with kpf alias)
  kpf --prompt (or -p)                          # Interactive service selection
  kpf --prompt -n production                    # Interactive selection in specific namespace
  kpf --all (or -A)                             # Show all services across all namespaces
  kpf --all-ports (or -l)                       # Show all services with their ports
  kpf --prompt --check -n production            # Interactive selection with endpoint status
        """,
    )

    parser.add_argument("--version", "-v", action="version", version=f"kpf {__version__}")

    parser.add_argument(
        "--prompt",
        "-p",
        action="store_true",
        help="Interactive service selection with colored table",
    )

    parser.add_argument(
        "--namespace",
        "-n",
        type=str,
        help="Kubernetes namespace to use (default: current context namespace)",
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
        "-0",
        dest="address_zero",
        action="store_true",
        help="Listen on all interfaces (0.0.0.0) instead of localhost",
    )

    # Positional arguments for legacy port-forward syntax
    parser.add_argument("args", nargs="*", help="kubectl port-forward arguments (legacy mode)")

    return parser


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

    try:
        port_forward_args = None

        # Handle interactive modes
        if args.prompt or args.all or args.all_ports or args.check:
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
            parser.print_help()
            sys.exit(0)

        # Apply the -0 flag if specified
        if args.address_zero and port_forward_args:
            # Check if --address is already specified to avoid duplicates/conflicts
            if "--address" not in port_forward_args:
                port_forward_args.extend(["--address", "0.0.0.0"])

        # Run the port-forward utility (should only reach here if port_forward_args is set)
        if port_forward_args:
            run_port_forward(port_forward_args, debug_mode=args.debug)

    except KeyboardInterrupt:
        console.print("\nOperation cancelled by user (Ctrl+C)", style="yellow")
        sys.exit(0)
    except Exception as e:
        console.print(f"Error: {e}", style="red")
        sys.exit(1)


if __name__ == "__main__":
    main()
