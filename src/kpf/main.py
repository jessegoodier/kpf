#!/usr/bin/env python3

import re
import socket
import subprocess
import sys
import threading
import time

from rich.console import Console

# Initialize Rich console
console = Console()

restart_event = threading.Event()
shutdown_event = threading.Event()

# Global debug state
_debug_enabled = False


class Debug:
    @staticmethod
    def print(message: str):
        if _debug_enabled:
            console.print(f"[dim cyan][DEBUG][/dim cyan] {message}")


debug = Debug()


def _is_port_available(port: int) -> bool:
    """Check if a port is available on localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("localhost", port))
            return True
    except OSError:
        return False


def _extract_local_port(port_forward_args):
    """Extract local port from port-forward arguments like '8080:80' -> 8080."""
    for arg in port_forward_args:
        if ":" in arg and not arg.startswith("-"):
            try:
                local_port_str, _ = arg.split(":", 1)
                return int(local_port_str)
            except (ValueError, IndexError):
                continue
    return None


def _validate_port_availability(port_forward_args):
    """Validate that the local port in port-forward args is available."""
    local_port = _extract_local_port(port_forward_args)
    if local_port is None:
        debug.print("Could not extract local port from arguments")
        return True  # Can't validate, let kubectl handle it
    
    if not _is_port_available(local_port):
        console.print(f"[red]Error: Local port {local_port} is already in use[/red]")
        console.print(f"[yellow]Please choose a different port or free up port {local_port}[/yellow]")
        return False
    
    debug.print(f"Port {local_port} is available")
    return True


def _test_port_forward_health(port_forward_args, timeout: int = 10):
    """Test if port-forward is working by checking if the local port becomes active."""
    local_port = _extract_local_port(port_forward_args)
    if local_port is None:
        debug.print("Could not extract local port for health check")
        return True  # Can't test, assume it's working
    
    debug.print(f"Testing port-forward health on port {local_port}")
    
    # Wait for port to become active (kubectl port-forward takes a moment to start)
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # Try to connect to the port to see if it's active
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex(("localhost", local_port))
                if result == 0 or result == 61:  # Connected or connection refused (service may be down but port-forward is working)
                    debug.print(f"Port-forward appears to be working on port {local_port}")
                    return True
        except (OSError, socket.error):
            pass
        
        time.sleep(0.5)
    
    debug.print(f"Port-forward health check failed - port {local_port} not responding after {timeout}s")
    return False


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
    namespace = "default"
    resource_name = None

    # Find namespace
    try:
        n_index = port_forward_args.index("-n")
        if n_index + 1 < len(port_forward_args):
            namespace = port_forward_args[n_index + 1]
            debug.print(f"Found namespace in args: {namespace}")
    except ValueError:
        # '-n' flag not found, use default namespace
        debug.print("No namespace specified, using 'default'")

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


def port_forward_thread(args):
    """
    This thread runs the kubectl port-forward command.
    It listens for the `restart_event` and restarts the process when it's set.
    """
    debug.print(f"Port-forward thread started with args: {args}")
    proc = None
    while not shutdown_event.is_set():
        try:
            console.print(
                f"\n[green][Port-Forwarder] Starting: kubectl port-forward {' '.join(args)}[/green]"
            )
            debug.print(f"Executing: kubectl port-forward {' '.join(args)}")
            proc = subprocess.Popen(
                ["kubectl", "port-forward"] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            debug.print(f"Port-forward process started with PID: {proc.pid}")

            # Give port-forward a moment to start, then test if it's working
            time.sleep(2)
            
            # Test if port-forward is healthy
            if not _test_port_forward_health(args):
                console.print("[red]Port-forward failed to start properly[/red]")
                console.print("[yellow]This may indicate the service is not running or the port mapping is incorrect[/yellow]")
                if proc:
                    proc.terminate()
                    proc.wait(timeout=5)
                shutdown_event.set()
                return

            # Wait for either a restart signal or a shutdown signal
            # The timeout prevents blocking forever and allows the loop to check for shutdown_event
            while not restart_event.is_set() and not shutdown_event.is_set():
                time.sleep(1)

            if proc:
                console.print(
                    f"[green][Port-Forwarder] Change detected on {args}. Restarting process...[/green]"
                )
                debug.print(f"Terminating port-forward process PID: {proc.pid}")
                proc.terminate()  # Gracefully terminate the process
                proc.wait(timeout=5)  # Wait for it to shut down
                if proc.poll() is None:
                    debug.print("Process did not terminate gracefully, force killing")
                    proc.kill()  # Force kill if it's still running
                    console.print("[red][Port-Forwarder] Process was forcefully killed.[/red]")
                else:
                    debug.print("Process terminated gracefully")
                proc = None

            restart_event.clear()  # Reset the event for the next cycle

        except Exception as e:
            console.print(f"[red][Port-Forwarder] An error occurred: {e}[/red]")
            if proc:
                proc.kill()
            shutdown_event.set()
            return

    if proc:
        proc.kill()


def endpoint_watcher_thread(namespace, resource_name):
    """
    This thread watches the specified endpoint for changes.
    When a change is detected, it sets the `restart_event`.
    """
    debug.print(f"Endpoint watcher thread started for {namespace}/{resource_name}")
    proc = None
    while not shutdown_event.is_set():
        try:
            console.print(
                f"[green][Watcher] Starting watcher for endpoint changes for '{namespace}/{resource_name}'...[/green]"
            )
            command = [
                "kubectl",
                "get",
                "--no-headers",
                "ep",
                "-w",
                "-n",
                namespace,
                resource_name,
            ]
            debug.print(f"Executing endpoint watcher command: {' '.join(command)}")

            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            debug.print(f"Endpoint watcher process started with PID: {proc.pid}")

            # The `for` loop will block and yield lines as they are produced
            # by the subprocess's stdout.
            is_first_line = True
            for line in proc.stdout:
                if shutdown_event.is_set():
                    break
                debug.print(f"Endpoint watcher received line: {line.strip()}")
                # The first line is the table header, which we should ignore.
                if is_first_line:
                    is_first_line = False
                    debug.print("Skipping first line (header)")
                    continue
                else:
                    debug.print("Endpoint change detected, setting restart event")
                    debug.print(f"Endpoint change details: {line.strip()}")
                restart_event.set()

            # If the subprocess finishes, we should break out and restart the watcher
            # This handles cases where the kubectl process itself might terminate.
            proc.wait()

        except Exception as e:
            console.print(f"[red][Watcher] An error occurred: {e}[/red]")
            if proc:
                proc.kill()
            shutdown_event.set()
            return

    if proc:
        proc.kill()


def run_port_forward(port_forward_args, debug_mode: bool = False):
    """
    The main function to orchestrate the two threads.
    """
    global _debug_enabled
    _debug_enabled = debug_mode

    console.print("kpf: Kubectl Port-Forward Restarter Utility")
    debug.print("Debug mode enabled")

    # Validate port availability before starting
    if not _validate_port_availability(port_forward_args):
        sys.exit(1)

    # Get watcher arguments from the port-forwarding args
    namespace, resource_name = get_watcher_args(port_forward_args)
    debug.print(f"Parsed namespace: {namespace}, resource_name: {resource_name}")

    console.print(f"Port-forward arguments: {port_forward_args}")
    console.print(f"Endpoint watcher target: namespace={namespace}, resource_name={resource_name}")

    # Create and start the two threads
    debug.print("Creating port-forward and endpoint watcher threads")
    pf_t = threading.Thread(target=port_forward_thread, args=(port_forward_args,))
    ew_t = threading.Thread(
        target=endpoint_watcher_thread,
        args=(
            namespace,
            resource_name,
        ),
    )

    debug.print("Starting threads")
    pf_t.start()
    ew_t.start()

    try:
        # Keep the main thread alive while the other threads are running
        while pf_t.is_alive() and ew_t.is_alive():
            time.sleep(1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Ctrl+C detected. Shutting down gracefully...[/yellow]")
        console.print("[yellow]Press Ctrl+C again to force exit.[/yellow]")
        debug.print("KeyboardInterrupt received, initiating graceful shutdown")

    finally:
        # Signal a graceful shutdown
        debug.print("Setting shutdown event")
        shutdown_event.set()

        # Wait for both threads to finish
        debug.print("Waiting for threads to finish...")
        pf_t.join()
        ew_t.join()
        debug.print("All threads have shut down")
        console.print("[Main] All threads have shut down. Exiting.")


def main():
    """Legacy main function for backward compatibility."""
    port_forward_args = get_port_forward_args(sys.argv[1:])
    run_port_forward(port_forward_args)


if __name__ == "__main__":
    main()
