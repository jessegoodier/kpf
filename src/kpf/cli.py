#!/usr/bin/env python3

import argparse
import sys
from typing import List, Optional

from . import __version__
from .kubernetes import KubernetesClient
from .display import ServiceSelector
from .main import run_port_forward


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="kpf",
        description="Kubectl Port-Forward Restarter Utility - automatically restart port-forwards when endpoints change",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  kpf svc/frontend 8080:8080 -n production     # Direct port-forward (legacy mode)
  kpf --prompt                                  # Interactive service selection
  kpf --prompt -n production                    # Interactive selection in specific namespace
  kpf --all                                     # Show all services across all namespaces
  kpf --all-ports                              # Show all services with their ports
        """
    )
    
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"kpf {__version__}"
    )
    
    parser.add_argument(
        "--prompt", "-p",
        action="store_true",
        help="Interactive service selection with colored table (green=has endpoints, red=no endpoints)"
    )
    
    parser.add_argument(
        "--namespace", "-n",
        type=str,
        help="Kubernetes namespace to use (default: current context namespace)"
    )
    
    parser.add_argument(
        "--all", "-A",
        action="store_true",
        help="Show all services across all namespaces in a sorted table"
    )
    
    parser.add_argument(
        "--all-ports", "-l",
        action="store_true",
        help="Include ports from pods, deployments, daemonsets, etc."
    )
    
    # Positional arguments for legacy port-forward syntax
    parser.add_argument(
        "args",
        nargs="*",
        help="kubectl port-forward arguments (legacy mode)"
    )
    
    return parser


def handle_prompt_mode(namespace: Optional[str] = None, show_all: bool = False, show_all_ports: bool = False) -> List[str]:
    """Handle interactive service selection."""
    k8s_client = KubernetesClient()
    selector = ServiceSelector(k8s_client)
    
    if show_all:
        return selector.select_service_all_namespaces(show_all_ports)
    else:
        return selector.select_service_in_namespace(namespace, show_all_ports)


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    try:
        # Handle interactive modes
        if args.prompt or args.all or args.all_ports:
            port_forward_args = handle_prompt_mode(
                namespace=args.namespace,
                show_all=args.all,
                show_all_ports=args.all_ports
            )
            if not port_forward_args:
                print("No service selected. Exiting.")
                sys.exit(0)
        
        # Handle legacy mode
        elif args.args:
            port_forward_args = args.args
            # Add namespace if specified
            if args.namespace and "-n" not in port_forward_args:
                port_forward_args.extend(["-n", args.namespace])
        
        else:
            parser.print_help()
            sys.exit(1)
        
        # Run the port-forward utility
        run_port_forward(port_forward_args)
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()