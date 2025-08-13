#!/usr/bin/env python3

import re
import signal
import socket
import subprocess
import sys
import threading
import time
from enum import Enum
from typing import Tuple

import requests
from rich.console import Console

# Initialize Rich console
console = Console()

restart_event = threading.Event()
shutdown_event = threading.Event()

# Track last restart time for throttling
_last_restart_time = 0
RESTART_THROTTLE_SECONDS = 5

# Track connectivity failure state
_connectivity_failure_start_time = None
CONNECTIVITY_CHECK_INTERVAL = 2.0  # Check every 2 seconds minimum
CONNECTIVITY_FAILURE_TIMEOUT = 10.0  # Exit after 10 seconds of failures
HTTP_TIMEOUT = 3.0  # HTTP request timeout
HTTP_RETRY_INTERVAL = 2.0  # Minimum interval between HTTP retries

# Connection health tracking
_last_http_attempt_time = 0

# Debug message rate limiting
_debug_message_timestamps = {}
DEBUG_MESSAGE_INTERVAL = 2.0  # Minimum interval between repeated debug messages

# HTTP timeout specific tracking
_http_timeout_start_time = None
HTTP_TIMEOUT_RESTART_THRESHOLD = 5.0  # Restart if HTTP timeouts persist for 5 seconds


class ConnectivityTestResult(Enum):
    """Result of connectivity testing."""

    SUCCESS = "success"
    SOCKET_FAILURE = "socket_failure"
    HTTP_CONNECTION_ERROR = "http_connection_error"
    HTTP_TIMEOUT = "http_timeout"
    UNKNOWN_ERROR = "unknown_error"


# Global debug state
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


def _validate_port_format(port_forward_args):
    """Validate that port mappings in arguments are valid integers."""
    for arg in port_forward_args:
        if ":" in arg and not arg.startswith("-"):
            try:
                parts = arg.split(":")
                if len(parts) < 2:
                    continue

                local_port_str = parts[0]
                remote_port_str = parts[1]

                # Validate local port
                local_port = int(local_port_str)
                if not (1 <= local_port <= 65535):
                    console.print(
                        f"[red]Error: Local port {local_port} is not in valid range (1-65535)[/red]"
                    )
                    return False

                # Validate remote port
                remote_port = int(remote_port_str)
                if not (1 <= remote_port <= 65535):
                    console.print(
                        f"[red]Error: Remote port {remote_port} is not in valid range (1-65535)[/red]"
                    )
                    return False

                debug.print(
                    f"Port format validation [green]passed: {local_port}:{remote_port}[/green]"
                )
                return True

            except (ValueError, IndexError) as e:
                console.print(
                    f"[red]Error: Invalid port format in '{arg}'. Expected format: 'local_port:remote_port' (e.g., 8080:80)[/red]"
                )
                debug.print(f"Port format validation [red]failed for '{arg}': {e}[/red]")
                return False

    # No port mapping found
    console.print(
        "[red]Error: No valid port mapping found. Expected format: 'local_port:remote_port' (e.g., 8080:80)[/red]"
    )
    return False


def _validate_kubectl_command(port_forward_args):
    """Validate that kubectl is available and basic resource syntax is correct."""
    try:
        # First check if kubectl is available
        result = subprocess.run(
            ["kubectl", "version", "--client"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            console.print("[red]Error: kubectl is not working properly[/red]")
            console.print(
                f"[yellow]kubectl error: {result.stderr.strip() if result.stderr else 'Unknown error'}[/yellow]"
            )
            return False

        debug.print("[green]kubectl client is available[/green]")

        # Basic validation of resource format (svc/name, pod/name, etc.)
        resource_found = False
        for arg in port_forward_args:
            if "/" in arg and not arg.startswith("-"):
                resource_parts = arg.split("/", 1)
                if len(resource_parts) == 2:
                    resource_type = resource_parts[0].lower()
                    resource_name = resource_parts[1]

                    # Check for valid resource types
                    valid_types = [
                        "svc",
                        "service",
                        "pod",
                        "deploy",
                        "deployment",
                        "rs",
                        "replicaset",
                    ]
                    if resource_type in valid_types and resource_name:
                        resource_found = True
                        debug.print(
                            f"Valid resource format found: [green]{resource_type}/{resource_name}[/green]"
                        )
                        break

        if not resource_found:
            console.print("[red]Error: No valid resource specified[/red]")
            console.print(
                "[yellow]Expected format: 'svc/service-name', 'pod/pod-name', etc.[/yellow]"
            )
            return False

        debug.print("[green]kubectl command validation passed[/green]")
        return True

    except subprocess.TimeoutExpired:
        console.print("[red]Error: kubectl command validation timed out[/red]")
        console.print("[yellow]This may indicate kubectl is not responding[/yellow]")
        return False
    except FileNotFoundError:
        console.print("[red]Error: kubectl command not found[/red]")
        console.print("[yellow]Please install kubectl and ensure it's in your PATH[/yellow]")
        return False
    except Exception as e:
        console.print(f"[red]Error: Failed to validate kubectl command: {e}[/red]")
        debug.print(f"kubectl validation exception: {e}")
        return False


def _validate_service_and_endpoints(port_forward_args):
    """Validate that the target service exists and has endpoints."""
    try:
        # Extract namespace and resource info
        namespace = "default"
        resource_type = None
        resource_name = None

        # Find namespace
        try:
            n_index = port_forward_args.index("-n")
            if n_index + 1 < len(port_forward_args):
                namespace = port_forward_args[n_index + 1]
        except ValueError:
            pass

        # Find resource
        for arg in port_forward_args:
            if "/" in arg and not arg.startswith("-"):
                parts = arg.split("/", 1)
                if len(parts) == 2:
                    resource_type = parts[0].lower()
                    resource_name = parts[1]
                    break

        if not resource_name:
            debug.print("No resource found for service validation")
            return True  # Let kubectl handle it

        debug.print(f"Validating {resource_type}/{resource_name} in namespace {namespace}")

        # For services, check if service exists and has endpoints
        if resource_type in ["svc", "service"]:
            # Check if service exists
            cmd_service = [
                "kubectl",
                "get",
                "svc",
                resource_name,
                "-n",
                namespace,
                "-o",
                "json",
            ]
            result = subprocess.run(cmd_service, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                console.print(
                    f"[red]Error: Service '{resource_name}' not found in namespace '{namespace}'[/red]"
                )
                if "not found" in error_msg.lower():
                    console.print(
                        "[yellow]Check the service name and namespace, or create the service first[/yellow]"
                    )
                else:
                    console.print(f"[yellow]kubectl error: {error_msg}[/yellow]")
                return False

            debug.print(f"Service {resource_name} exists")

            # Check if service has endpoints
            cmd_endpoints = [
                "kubectl",
                "get",
                "endpoints",
                resource_name,
                "-n",
                namespace,
                "-o",
                "json",
            ]
            result = subprocess.run(cmd_endpoints, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                console.print(f"[red]Error: No endpoints found for service '{resource_name}'[/red]")
                console.print(
                    "[yellow]This usually means no pods are running for this service[/yellow]"
                )
                console.print(
                    "[yellow]Check if pods are running: kubectl get pods -n {namespace}[/yellow]".replace(
                        "{namespace}", namespace
                    )
                )
                return False

            # Parse endpoints to see if any exist
            try:
                import json

                endpoints_data = json.loads(result.stdout)
                subsets = endpoints_data.get("subsets", [])

                has_ready_endpoints = False
                for subset in subsets:
                    addresses = subset.get("addresses", [])
                    if addresses:
                        has_ready_endpoints = True
                        break

                if not has_ready_endpoints:
                    console.print(
                        f"[red]Error: Service '{resource_name}' has no ready endpoints[/red]"
                    )
                    console.print(
                        "[yellow]This means the service exists but no pods are ready to serve traffic[/yellow]"
                    )
                    console.print(
                        f"[yellow]Check pod status: kubectl get pods -n {namespace} -l <service-selector>[/yellow]"
                    )
                    return False

                debug.print(f"Service {resource_name} has ready endpoints")

            except (json.JSONDecodeError, KeyError) as e:
                debug.print(f"Failed to parse endpoints JSON: {e}")
                console.print(
                    "[yellow]Warning: Could not validate endpoints, proceeding anyway[/yellow]"
                )

        # For pods/deployments, check if they exist (simpler check)
        elif resource_type in ["pod", "deploy", "deployment"]:
            kubectl_resource = (
                "deployment" if resource_type in ["deploy", "deployment"] else resource_type
            )
            cmd = ["kubectl", "get", kubectl_resource, resource_name, "-n", namespace]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                console.print(
                    f"[red]Error: {kubectl_resource.capitalize()} '{resource_name}' not found in namespace '{namespace}'[/red]"
                )
                console.print(f"[yellow]kubectl error: {error_msg}[/yellow]")
                return False

            debug.print(f"{kubectl_resource.capitalize()} {resource_name} exists")

        debug.print("[green]Service and endpoints validation passed[/green]")
        return True

    except subprocess.TimeoutExpired:
        console.print("[red]Error: Service validation timed out[/red]")
        console.print("[yellow]This may indicate kubectl is not responding[/yellow]")
        return False
    except Exception as e:
        console.print(f"[red]Error: Failed to validate service: {e}[/red]")
        debug.print(f"Service validation exception: {e}")
        return False


def _validate_port_availability(port_forward_args):
    """Validate that the local port in port-forward args is available."""
    local_port = _extract_local_port(port_forward_args)
    if local_port is None:
        debug.print("Could not extract local port from arguments")
        return True  # Can't validate, let kubectl handle it

    if not _is_port_available(local_port):
        console.print(f"[red]Error: Local port {local_port} is already in use[/red]")
        console.print(
            f"[yellow]Please choose a different port or free up port {local_port}[/yellow]"
        )
        return False

    debug.print(f"[green]Port {local_port} is available[/green]")
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
                if result == 0:
                    # Connected (0) or connection refused (61) - both mean port-forward is working
                    debug.print(
                        f"Port-forward appears to be working on port {local_port} [green](result: {result})[/green]"
                    )
                    return True
                elif result == 61:
                    # TODO: not sure how to handle this case
                    debug.print(
                        f"Port-forward health check failed on port {local_port} [red](result: {result})[/red]"
                    )
                    # return False # don't return false here, we want to keep trying
                else:
                    debug.print(
                        f"Port-forward health check failed on port {local_port} [red](result: {result})[/red]"
                    )
                    # return False # don't return false here, we want to keep trying
        except (OSError, socket.error):
            pass

        time.sleep(0.5)

    debug.print(
        f"Port-forward health check failed - port {local_port} not responding after {timeout}s"
    )
    return False


def _test_socket_connectivity(local_port: int) -> Tuple[bool, str]:
    """Test basic socket connectivity to the port.

    Returns:
        Tuple[bool, str]: (success, error_description)
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)  # Short timeout for connectivity check
            result = sock.connect_ex(("localhost", local_port))

            # Connection codes we consider successful:
            # 0 = Connected successfully
            # 61 (ECONNREFUSED) = Port is open but service refused connection (service may be down but port-forward works)
            if result == 0:
                debug.print(
                    f"Socket connectivity test: Connected [green]successfully (code: {result})[/green]"
                )
                return True, "connected"
            elif result == 61:  # ECONNREFUSED on macOS/Linux
                debug.print(
                    f"Socket connectivity test: Connection [red]refused - port-forward working, service may be down (code: {result})[/red]"
                )
                return (
                    True,
                    "connection_refused",
                )  # but there is a port-forward working
            else:
                debug.print(f"Socket connectivity test failed (code: {result})")
                return False, f"connection_error_{result}"

    except (OSError, socket.error) as e:
        debug.print(f"Socket connectivity test failed with exception: {e}")
        return False, f"socket_exception_{type(e).__name__}"


def _test_http_connectivity(local_port: int) -> Tuple[ConnectivityTestResult, str]:
    """Test HTTP connectivity to the port.

    This function attempts both HTTP and HTTPS requests to the local port.
    Any response (including 404, 500, etc.) is considered successful as it proves
    the port-forward is working and traffic is reaching the service.

    Returns:
        Tuple[ConnectivityTestResult, str]: (result, description)
    """
    global _last_http_attempt_time

    current_time = time.time()

    # Rate limit HTTP requests
    if current_time - _last_http_attempt_time < HTTP_RETRY_INTERVAL:
        debug.print("HTTP connectivity test rate limited")
        return ConnectivityTestResult.SUCCESS, "rate_limited"

    _last_http_attempt_time = current_time

    # Try both HTTP and HTTPS
    urls = [f"http://localhost:{local_port}", f"https://localhost:{local_port}"]

    for url in urls:
        try:
            debug.print(f"Attempting HTTP connectivity test: {url}")

            # Make request with short timeout and disabled SSL verification
            response = requests.get(
                url,
                timeout=HTTP_TIMEOUT,
                verify=False,  # Don't verify SSL for localhost
                allow_redirects=False,  # Don't follow redirects for faster response
            )

            # Any HTTP response code is considered success
            # (200, 404, 500, etc. all mean the service is reachable)
            debug.print(
                f"HTTP connectivity test [green]successful: {url} -> {response.status_code}[/green]"
            )
            _mark_http_timeout_end()  # Reset timeout tracking on success
            return (
                ConnectivityTestResult.SUCCESS,
                f"http_response_{response.status_code}",
            )

        except requests.exceptions.ConnectTimeout:
            debug.print(f"HTTP connectivity test [red]timeout: {url}[/red]")
            _mark_http_timeout_start()  # Track timeout start
            continue  # Try next URL

        except requests.exceptions.ConnectionError as e:
            debug.print(f"HTTP connectivity test [red]connection error: {url} -> {e}[/red]")
            continue  # Try next URL

        except requests.exceptions.Timeout:
            debug.print(f"HTTP connectivity test [red]timeout: {url}[/red]")
            _mark_http_timeout_start()  # Track timeout start
            continue  # Try next URL

        except Exception as e:
            debug.print(f"HTTP connectivity test [red]unexpected error: {url} -> {e}[/red]")
            continue  # Try next URL

    # If we get here, all HTTP attempts failed
    return ConnectivityTestResult.HTTP_CONNECTION_ERROR, "all_http_attempts_failed"


def _check_port_connectivity(local_port: int) -> bool:
    """Check port-forward connectivity using socket and HTTP tests.

    Semantics:
    - Returns True when the port-forward plumbing is healthy (socket connects
      or is explicitly refused), regardless of the upstream service being ready.
    - Returns False only when the port-forward path appears broken (socket
      failures), which should trigger recovery behavior.

    Additionally, when the socket connects successfully, we attempt an HTTP
    request to determine if the upstream service is responding. An HTTP failure
    will NOT be treated as a port-forward failure, but will be surfaced via
    debug logs.

    Args:
        local_port: The local port to test

    Returns:
        bool: True if port-forward is healthy; False if port-forward is broken
    """
    global _connectivity_failure_start_time

    if local_port is None:
        debug.print("No local port specified, skipping connectivity check")
        return True  # Can't test, assume it's working

    debug.print(f"Starting enhanced connectivity check for port {local_port}", rate_limit=True)

    # Step 1: Basic socket connectivity test
    socket_success, socket_description = _test_socket_connectivity(local_port)

    if not socket_success:
        debug.print(f"Socket connectivity [red]failed: {socket_description}[/red]")
        _mark_connectivity_failure(f"socket_failure: {socket_description}")
        return False

    debug.print(f"Socket connectivity [green]passed: {socket_description}[/green]")

    # Step 2: If socket connected successfully (not just refused), test HTTP
    if socket_description == "connected":
        http_result, http_description = _test_http_connectivity(local_port)

        if http_result == ConnectivityTestResult.SUCCESS:
            debug.print(f"HTTP connectivity [green]passed: {http_description}[/green]")
            _mark_connectivity_success()
            return True
        else:
            debug.print(f"HTTP connectivity [yellow]issue: {http_description}[/yellow]")
            # HTTP failure when socket works indicates service issues,
            # but we still consider the port-forward itself healthy.
            _mark_connectivity_success()
            return True
    else:
        # Socket connection was refused - port-forward is working
        # but service is not responding (which is OK)
        debug.print(
            "[yellow]Connection refused - port-forward working, service not responding[/yellow]"
        )
        _mark_connectivity_success()
        return True


def _mark_connectivity_failure(reason: str):
    """Mark the start of a connectivity failure period."""
    global _connectivity_failure_start_time

    if _connectivity_failure_start_time is None:
        _connectivity_failure_start_time = time.time()
        debug.print(f"Port connectivity failure started: {reason}")


def _mark_connectivity_success():
    """Mark successful connectivity, resetting failure tracking."""
    global _connectivity_failure_start_time

    if _connectivity_failure_start_time is not None:
        failure_duration = time.time() - _connectivity_failure_start_time
        debug.print(f"[green]Port connectivity restored after {failure_duration:.1f}s[/green]")
        _connectivity_failure_start_time = None
    # Also reset HTTP timeout tracking on successful connectivity
    _mark_http_timeout_end()


def _check_connectivity_failure_timeout():
    """Check if connectivity has been failing for too long and should trigger program exit."""
    global _connectivity_failure_start_time

    if _connectivity_failure_start_time is None:
        return False  # No failure in progress

    failure_duration = time.time() - _connectivity_failure_start_time
    return failure_duration >= CONNECTIVITY_FAILURE_TIMEOUT


def _get_connectivity_failure_duration():
    """Get the duration of the current connectivity failure."""
    if _connectivity_failure_start_time is None:
        return 0
    return time.time() - _connectivity_failure_start_time


def _mark_http_timeout_start():
    """Mark the start of an HTTP timeout period."""
    global _http_timeout_start_time
    if _http_timeout_start_time is None:
        _http_timeout_start_time = time.time()
        debug.print("HTTP timeout period started")


def _mark_http_timeout_end():
    """Mark the end of HTTP timeout issues."""
    global _http_timeout_start_time
    if _http_timeout_start_time is not None:
        timeout_duration = time.time() - _http_timeout_start_time
        debug.print(f"[green]HTTP timeouts resolved after {timeout_duration:.1f}s[/green]")
        _http_timeout_start_time = None


def _check_http_timeout_restart():
    """Check if HTTP timeouts have been persistent and should trigger restart."""
    global _http_timeout_start_time
    if _http_timeout_start_time is None:
        return False  # No timeout in progress

    timeout_duration = time.time() - _http_timeout_start_time
    if timeout_duration >= HTTP_TIMEOUT_RESTART_THRESHOLD:
        debug.print(
            f"[yellow]HTTP timeouts persisted for {timeout_duration:.1f}s, triggering restart[/yellow]"
        )
        return True
    return False


def _should_restart_port_forward():
    """Check if enough time has passed since last restart to allow another restart."""
    global _last_restart_time
    current_time = time.time()
    time_since_last_restart = current_time - _last_restart_time

    if time_since_last_restart >= RESTART_THROTTLE_SECONDS:
        _last_restart_time = current_time
        return True
    else:
        remaining_time = RESTART_THROTTLE_SECONDS - time_since_last_restart
        debug.print(f"[yellow]Restart throttled: {remaining_time:.1f}s remaining[/yellow]")
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
    It also monitors port connectivity every 5 seconds and restarts if connection fails.
    """
    debug.print(f"Port-forward thread started with args: {args}")
    proc = None
    local_port = _extract_local_port(args)

    while not shutdown_event.is_set():
        try:
            console.print(f"\nDirect command: [cyan]kpf {' '.join(args)}[/cyan]\n")
            # Display URL before starting
            if local_port:
                console.print(
                    f"[light_blue][link=http://localhost:{local_port}]http://localhost:{local_port}[/link][/light_blue]"
                )

            debug.print(
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
                console.print(
                    "[yellow]This may indicate the service is not running or the port mapping is incorrect[/yellow]"
                )
                if proc:
                    proc.terminate()
                    proc.wait(timeout=5)
                shutdown_event.set()
                return

            console.print("\n🚀 [green]port-forward started[/green] 🚀")

            # Main loop: wait for restart signal or shutdown, checking connectivity periodically
            last_connectivity_check = time.time()

            while not restart_event.is_set() and not shutdown_event.is_set():
                current_time = time.time()

                # Check if it's time to test connectivity (minimum 2 seconds between checks)
                if current_time - last_connectivity_check >= CONNECTIVITY_CHECK_INTERVAL:
                    debug.print(
                        f"Checking port connectivity on port {local_port}",
                        rate_limit=True,
                    )

                    if not _check_port_connectivity(local_port):
                        failure_duration = _get_connectivity_failure_duration()
                        console.print(
                            f"[red]Port-forward connection failed on port {local_port}[/red]"
                        )
                        console.print(
                            f"[yellow]Failed to establish a new connection (failing for {failure_duration:.1f}s)[/yellow]"
                        )

                        # Check if we've been failing for too long
                        if _check_connectivity_failure_timeout():
                            console.print(
                                f"[red]Port-forward has been failing for {CONNECTIVITY_FAILURE_TIMEOUT}+ seconds[/red]"
                            )
                            console.print("[red]This usually indicates one of the following:[/red]")
                            console.print(
                                "[red]  • kubectl port-forward process died unexpectedly[/red]"
                            )
                            console.print(
                                "[red]  • Target service/pod is no longer available[/red]"
                            )
                            console.print(
                                "[red]  • Network connectivity issues to Kubernetes cluster[/red]"
                            )
                            console.print(
                                f"[red]  • Port {local_port} is being blocked or intercepted[/red]"
                            )
                            console.print(
                                "[yellow]Exiting kpf. Please check your service and cluster status.[/yellow]"
                            )
                            shutdown_event.set()
                            return

                        # Check if we should restart (throttling)
                        if _should_restart_port_forward():
                            restart_event.set()
                            break
                        else:
                            console.print(
                                f"[yellow]Restart throttled, will retry connectivity check in {CONNECTIVITY_CHECK_INTERVAL}s[/yellow]"
                            )
                    else:
                        debug.print(
                            f"Port connectivity check passed on port {local_port}",
                            rate_limit=True,
                        )

                    # Check if HTTP timeouts have persisted for too long and trigger restart
                    if _check_http_timeout_restart():
                        console.print(
                            "[yellow]HTTP connectivity timeouts persisting, restarting port-forward[/yellow]"
                        )
                        if _should_restart_port_forward():
                            restart_event.set()
                            break
                        else:
                            console.print(
                                f"[yellow]Restart throttled, will retry connectivity check in {CONNECTIVITY_CHECK_INTERVAL}s[/yellow]"
                            )

                    last_connectivity_check = current_time

                time.sleep(0.1)  # Short sleep for responsive shutdown

            if proc and (restart_event.is_set() or shutdown_event.is_set()):
                if restart_event.is_set():
                    console.print(
                        "[yellow][Port-Forwarder] Restarting port-forward process...[/yellow]"
                    )
                debug.print(f"Terminating port-forward process PID: {proc.pid}")
                proc.terminate()  # Gracefully terminate the process
                try:
                    proc.wait(timeout=1)  # Even shorter timeout for faster shutdown
                    debug.print("Process terminated gracefully")
                except subprocess.TimeoutExpired:
                    debug.print("Process did not terminate gracefully, force killing")
                    proc.kill()  # Force kill if it's still running
                    console.print("[red][Port-Forwarder] Process was forcefully killed.[/red]")
                    try:
                        proc.wait(timeout=0.5)  # Brief wait after kill
                    except subprocess.TimeoutExpired:
                        debug.print("Process still not responding after kill")
                        pass
                proc = None

            restart_event.clear()  # Reset the event for the next cycle

        except Exception as e:
            console.print(f"[red][Port-Forwarder] An error occurred: {e}[/red]")
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
            shutdown_event.set()
            return

    if proc:
        debug.print("Final cleanup: terminating port-forward process")
        proc.terminate()
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            debug.print("Final cleanup: force killing port-forward process")
            proc.kill()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                debug.print("Port-forward process unresponsive even after kill")


def endpoint_watcher_thread(namespace, resource_name):
    """
    This thread watches the specified endpoint for changes.
    When a change is detected, it sets the `restart_event`.
    """
    debug.print(f"Endpoint watcher thread started for {namespace}/{resource_name}")
    proc = None
    while not shutdown_event.is_set():
        try:
            debug.print(
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
            debug.print(
                f"Executing endpoint watcher command: {' '.join(command)}",
                rate_limit=True,
            )

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
                    debug.print("Shutdown event detected in endpoint watcher, breaking")
                    break
                debug.print(f"Endpoint watcher received line: {line.strip()}", rate_limit=True)
                # The first line is the table header, which we should ignore.
                if is_first_line:
                    is_first_line = False
                    debug.print("Skipping first line (header)")
                    continue
                else:
                    debug.print("Endpoint change detected")
                    debug.print(f"Endpoint change details: {line.strip()}")

                    # Check if we should restart (throttling)
                    if _should_restart_port_forward():
                        console.print(
                            "[green][Watcher] Endpoint change detected, restarting port-forward...[/green]"
                        )
                        restart_event.set()
                    else:
                        console.print(
                            "[yellow][Watcher] Endpoint change detected, but restart throttled[/yellow]"
                        )

            # If the subprocess finishes, we should break out and restart the watcher
            # This handles cases where the kubectl process itself might terminate.
            proc.wait()

            # Add delay before restarting to prevent rapid kubectl process creation
            if not shutdown_event.is_set():
                debug.print(
                    "Endpoint watcher kubectl process ended, waiting 2s before restart",
                    rate_limit=True,
                )
                time.sleep(2)

        except Exception as e:
            console.print(f"[red][Watcher] An error occurred: {e}[/red]")
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass

            shutdown_event.set()
            return

    if proc:
        debug.print("Final cleanup: terminating endpoint watcher process")
        proc.terminate()
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            debug.print("Final cleanup: force killing endpoint watcher process")
            proc.kill()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                debug.print("Endpoint watcher process unresponsive even after kill")


def run_port_forward(port_forward_args, debug_mode: bool = False):
    """
    The main function to orchestrate the two threads.
    """
    global _debug_enabled
    _debug_enabled = debug_mode

    # console.print("kpf: kubectl port-forwarder")
    debug.print("Debug mode enabled")

    # Validate port format first
    if not _validate_port_format(port_forward_args):
        sys.exit(1)

    # Validate port availability
    if not _validate_port_availability(port_forward_args):
        sys.exit(1)

    # Validate kubectl command
    if not _validate_kubectl_command(port_forward_args):
        sys.exit(1)

    # Validate service exists and has endpoints
    if not _validate_service_and_endpoints(port_forward_args):
        sys.exit(1)

    # Get watcher arguments from the port-forwarding args
    namespace, resource_name = get_watcher_args(port_forward_args)
    debug.print(f"Parsed namespace: {namespace}, resource_name: {resource_name}")

    debug.print(f"Port-forward arguments: {port_forward_args}")
    debug.print(f"Endpoint watcher target: namespace={namespace}, resource_name={resource_name}")

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

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        # Keep the main thread alive while the other threads are running
        while pf_t.is_alive() and ew_t.is_alive() and not shutdown_event.is_set():
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
        pf_t.join(timeout=2)  # Reduced timeout
        ew_t.join(timeout=2)  # Reduced timeout

        if pf_t.is_alive() or ew_t.is_alive():
            debug.print("Some threads did not shut down cleanly, forcing exit")
            console.print("[yellow]Some threads did not shut down cleanly[/yellow]")
            console.print("[Main] Exiting.")
            # Force exit immediately instead of hanging
            import os

            os._exit(1)
        else:
            debug.print("All threads have shut down")
            console.print("[Main] Exiting.")


def main():
    """Legacy main function for backward compatibility."""
    port_forward_args = get_port_forward_args(sys.argv[1:])
    run_port_forward(port_forward_args)


if __name__ == "__main__":
    main()
