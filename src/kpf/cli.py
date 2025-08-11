#!/usr/bin/env python3

import argparse
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


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args, unknown_args = parser.parse_known_args()

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
            sys.exit(1)

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
