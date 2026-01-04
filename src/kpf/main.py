#!/usr/bin/env python3

import re
import signal
import sys
import threading
import time

from rich.console import Console

from .forwarder import PortForwarder
from .validators import (
    validate_kubectl_command,
    validate_port_availability,
    validate_port_format,
    validate_service_and_endpoints,
)
from .watcher import EndpointWatcher

# Initialize Rich console
console = Console()

restart_event = threading.Event()
shutdown_event = threading.Event()

# Debug message rate limiting
_debug_message_timestamps = {}
DEBUG_MESSAGE_INTERVAL = 2.0  # Minimum interval between repeated debug messages
_debug_enabled = False

# Track Ctrl+C presses for force exit
_sigint_count = 0


class Debug:
    @staticmethod
    def print(message: str, rate_limit: bool = False):
        """Print debug message with optional rate limiting.

        Args:
            message: The debug message to print
            rate_limit: If True, rate limit this message to once every DEBUG_MESSAGE_INTERVAL seconds
        """
        if not _debug_enabled:
            return

        if rate_limit:
            current_time = time.time()
            message_key = message[:50]  # Use first 50 chars as key to group similar messages

            last_time = _debug_message_timestamps.get(message_key, 0)
            if current_time - last_time < DEBUG_MESSAGE_INTERVAL:
                return  # Rate limited

            _debug_message_timestamps[message_key] = current_time

        console.print(f"[dim cyan][DEBUG][/dim cyan] {message}")


debug = Debug()


def _signal_handler(signum, frame):
    """Handle SIGINT (Ctrl+C) with force exit on second press."""
    global _sigint_count
    _sigint_count += 1

    if _sigint_count == 1:
        console.print("\n[yellow]Ctrl+C detected. Shutting down gracefully...[/yellow]")
        console.print("[yellow]Press Ctrl+C again to force exit.[/yellow]")
        debug.print("First SIGINT received, initiating graceful shutdown")
        shutdown_event.set()
    else:
        console.print("\n[red]Force exit requested. Terminating immediately...[/red]")
        debug.print("Second SIGINT received, forcing exit")
        sys.exit(1)


def get_port_forward_args(args):
    """
    Parses command-line arguments to extract the port-forward arguments.
    """
    if not args:
        print("Usage: python kpf.py <kubectl port-forward args>")
        sys.exit(1)
    return args


def get_watcher_args(port_forward_args):
    """
    Parses port-forward arguments to determine the namespace and resource name
    for the endpoint watcher command.
    Example: `['svc/frontend', '9090:9090', '-n', 'kubecost']` -> namespace='kubecost', resource_name='frontend'
    """
    debug.print(f"Parsing port-forward args: {port_forward_args}")
    namespace = None
    resource_name = None

    # Find namespace
    try:
        n_index = port_forward_args.index("-n")
        if n_index + 1 < len(port_forward_args):
            namespace = port_forward_args[n_index + 1]
            debug.print(f"Found namespace in args: {namespace}")
    except ValueError:
        # '-n' flag not found, use current context namespace
        from .kubernetes import KubernetesClient

        k8s_client = KubernetesClient()
        namespace = k8s_client.get_current_namespace()
        debug.print(f"No namespace specified, using current context namespace: '{namespace}'")

    # Find resource name (e.g., 'svc/frontend')
    for arg in port_forward_args:
        # Use regex to match patterns like 'svc/my-service' or 'pod/my-pod'
        match = re.match(r"(svc|service|pod|deploy|deployment)\/(.+)", arg)
        if match:
            # The resource name is the second group in the regex match
            resource_name = match.group(2)
            debug.print(f"Found resource: {match.group(1)}/{resource_name}")
            break

    if not resource_name:
        debug.print("ERROR: Could not determine resource name from args")
        console.print("Could not determine resource name for endpoint watcher.")
        sys.exit(1)

    debug.print(f"Final parsed values - namespace: {namespace}, resource_name: {resource_name}")
    return namespace, resource_name


def run_port_forward(port_forward_args, debug_mode: bool = False):
    """
    The main function to orchestrate the two threads.
    """
    global _debug_enabled
    _debug_enabled = debug_mode

    if debug_mode:
        debug.print("Debug mode enabled")

    # Validate port format first
    if not validate_port_format(port_forward_args):
        sys.exit(1)

    # Validate port availability
    if not validate_port_availability(port_forward_args, debug.print):
        sys.exit(1)

    # Validate kubectl command
    if not validate_kubectl_command(port_forward_args):
        sys.exit(1)

    # Validate service exists and has endpoints
    if not validate_service_and_endpoints(port_forward_args, debug.print):
        sys.exit(1)

    # Get watcher arguments from the port-forwarding args
    namespace, resource_name = get_watcher_args(port_forward_args)
    debug.print(f"Parsed namespace: {namespace}, resource_name: {resource_name}")

    debug.print(f"Port-forward arguments: {port_forward_args}")
    debug.print(f"Endpoint watcher target: namespace={namespace}, resource_name={resource_name}")

    # Create forwarder and watcher instances
    forwarder = PortForwarder(
        port_forward_args, shutdown_event, restart_event, debug_callback=debug.print
    )

    # define delegate method for watcher to check if it should trigger restart on forwarder
    def should_restart_delegate():
        return forwarder.should_restart_port_forward()

    watcher = EndpointWatcher(
        namespace,
        resource_name,
        shutdown_event,
        restart_event,
        should_restart_delegate,
        debug_callback=debug.print,
    )

    debug.print("Starting threads")
    forwarder.start()
    watcher.start()

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        # Keep the main thread alive while the other threads are running
        while forwarder.is_alive() and watcher.is_alive() and not shutdown_event.is_set():
            time.sleep(0.5)  # Check more frequently for shutdown

    except KeyboardInterrupt:
        # This should be handled by signal handler now, but keep as fallback
        debug.print("KeyboardInterrupt in main loop (fallback)")
        shutdown_event.set()

    finally:
        # Signal a graceful shutdown
        debug.print("Setting shutdown event")
        shutdown_event.set()

        # Wait for both threads to finish with timeout
        debug.print("Waiting for threads to finish...")
        forwarder.join(timeout=3)  # Give a bit more time for graceful shutdown
        watcher.join(timeout=3)

        threads_alive = []
        if forwarder.is_alive():
            threads_alive.append("port-forward")
        if watcher.is_alive():
            threads_alive.append("endpoint-watcher")

        if threads_alive:
            debug.print(f"Threads still running: {', '.join(threads_alive)}")
            console.print(
                f"[yellow]Some threads did not shut down cleanly: {', '.join(threads_alive)}[/yellow]"
            )

            # Try to forcefully kill any remaining kubectl processes using pkill
            try:
                import subprocess

                result = subprocess.run(
                    ["pkill", "-f", "kubectl port-forward"], capture_output=True, timeout=2
                )
                if result.returncode == 0:
                    debug.print("Killed remaining kubectl port-forward processes")
                else:
                    debug.print("No kubectl port-forward processes found to kill")
            except Exception as e:
                debug.print(f"Could not kill kubectl processes: {e}")

            console.print("[Main] Exiting.")
            # Force exit immediately instead of hanging
            import os

            os._exit(1)
        else:
            debug.print("All threads have shut down cleanly")
            console.print("[Main] Exiting.")


def main():
    """Legacy main function for backward compatibility."""
    port_forward_args = get_port_forward_args(sys.argv[1:])
    run_port_forward(port_forward_args)


if __name__ == "__main__":
    main()
