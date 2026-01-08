import socket
import subprocess

from rich.console import Console

console = Console()


class Debug:
    # Minimal debug shim if we don't want to import the full Debug class from main yet
    # Ideally we'd move Debug to a utilities module too, but for now we'll pass a debug function or use a simple one
    pass


def _debug_print(message, debug_enabled=False):
    if debug_enabled:
        console.print(f"[dim cyan][DEBUG][/dim cyan] {message}")


def extract_local_port(port_forward_args):
    """Extract local port from port-forward arguments like '8080:80' -> 8080."""
    for arg in port_forward_args:
        if ":" in arg and not arg.startswith("-"):
            try:
                local_port_str, _ = arg.split(":", 1)
                return int(local_port_str)
            except (ValueError, IndexError):
                continue
    return None


def is_port_available(port: int) -> tuple[bool, str]:
    """Check if a port is available on localhost.

    Returns:
        tuple[bool, str]: (is_available, error_reason)
        error_reason can be 'permission', 'in_use', or ''
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("localhost", port))
            return True, ""
    except OSError as e:
        # Check if it's a permission error
        # errno 1 (EPERM) - Operation not permitted
        # errno 13 (EACCES) - Permission denied (Unix)
        # errno 10013 (WSAEACCES) - Permission denied (Windows)
        if e.errno in (1, 13, 10013):
            return False, "permission"
        # errno 98 (EADDRINUSE) - Address already in use (Unix)
        # errno 10048 (WSAEADDRINUSE) - Address already in use (Windows)
        elif e.errno in (98, 10048):
            return False, "in_use"
        # For other errors on low ports, assume it might be a permission issue
        elif port < 1024:
            return False, "permission"
        else:
            return False, "in_use"


def find_next_free_port(start_port: int, max_attempts: int = 10):
    """Find the next available port starting from start_port.

    Args:
        start_port: Port number to start searching from
        max_attempts: Maximum number of ports to try (default: 10)

    Returns:
        int or None: The next available port, or None if no port found
    """
    for offset in range(max_attempts):
        port = start_port + offset
        if port > 65535:
            return None
        is_available, error_reason = is_port_available(port)
        # Only use ports that are truly available (not permission issues)
        if is_available:
            return port
    return None


def validate_port_format(port_forward_args):
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

                return True

            except (ValueError, IndexError):
                console.print(
                    f"[red]Error: Invalid port format in '{arg}'. Expected format: 'local_port:remote_port' (e.g., 8080:80)[/red]"
                )
                return False

    # No port mapping found
    console.print(
        "[red]Error: No valid port mapping found. Expected format: 'local_port:remote_port' (e.g., 8080:80)[/red]"
    )
    return False


def validate_kubectl_command(port_forward_args):
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
                        break

        if not resource_found:
            console.print("[red]Error: No valid resource specified[/red]")
            console.print(
                "[yellow]Expected format: 'svc/service-name', 'pod/pod-name', etc.[/yellow]"
            )
            return False

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
        return False


def validate_service_and_endpoints(port_forward_args, debug_callback=None):
    """Validate that the target service exists and has endpoints."""
    try:
        # Extract namespace and resource info
        namespace = None
        resource_type = None
        resource_name = None

        # Find namespace
        try:
            n_index = port_forward_args.index("-n")
            if n_index + 1 < len(port_forward_args):
                namespace = port_forward_args[n_index + 1]
        except ValueError:
            pass  # '-n' flag not found

        # If namespace not found or incomplete, use current context namespace
        if namespace is None:
            from .kubernetes import KubernetesClient

            k8s_client = KubernetesClient()
            namespace = k8s_client.get_current_namespace()

        # Find resource
        for arg in port_forward_args:
            if "/" in arg and not arg.startswith("-"):
                parts = arg.split("/", 1)
                if len(parts) == 2:
                    resource_type = parts[0].lower()
                    resource_name = parts[1]
                    break

        if not resource_name:
            if debug_callback:
                debug_callback("No resource found for service validation")
            return True  # Let kubectl handle it

        if debug_callback:
            debug_callback(f"Validating {resource_type}/{resource_name} in namespace {namespace}")

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

            if debug_callback:
                debug_callback(f"Service {resource_name} exists")

            # Parse service data to extract selector for later use
            service_selector_str = "<service-selector>"
            try:
                import json

                service_data = json.loads(result.stdout)
                selector = service_data.get("spec", {}).get("selector", {})
                if selector:
                    # Format selector as key=value,key=value
                    parts = [f"{k}={v}" for k, v in selector.items()]
                    service_selector_str = ",".join(parts)
            except (json.JSONDecodeError, KeyError) as e:
                if debug_callback:
                    debug_callback(f"Failed to parse service JSON: {e}")

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
                        f"[yellow]Check pod status: kubectl get pods -n {namespace} -l {service_selector_str}[/yellow]"
                    )
                    return False

                if debug_callback:
                    debug_callback(f"Service {resource_name} has ready endpoints")

            except (json.JSONDecodeError, KeyError) as e:
                if debug_callback:
                    debug_callback(f"Failed to parse endpoints JSON: {e}")
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

            if debug_callback:
                debug_callback(f"{kubectl_resource.capitalize()} {resource_name} exists")

        return True

    except subprocess.TimeoutExpired:
        console.print("[red]Error: Service validation timed out[/red]")
        console.print("[yellow]This may indicate kubectl is not responding[/yellow]")
        return False
    except Exception as e:
        console.print(f"[red]Error: Failed to validate service: {e}[/red]")
        return False


def validate_port_availability(port_forward_args, debug_callback=None, config=None):
    """Validate that the local port in port-forward args is available.

    Args:
        port_forward_args: List of port-forward arguments (will be modified if user accepts alternative)
        debug_callback: Optional debug callback function
        config: Optional config dict for auto-select feature

    Returns:
        bool: True if port is available or user accepts alternative, False otherwise
    """
    local_port = extract_local_port(port_forward_args)
    if local_port is None:
        if debug_callback:
            debug_callback("Could not extract local port from arguments")
        return True  # Can't validate, let kubectl handle it

    is_available, error_reason = is_port_available(local_port)

    if is_available:
        if debug_callback:
            debug_callback(f"[green]Port {local_port} is available[/green]")
        return True

    # Port is not available - check if it's a low port permission issue
    if error_reason == "permission" and local_port < 1024:
        suggested_port = local_port + 1000
        console.print(
            f"[yellow]Error: Port {local_port} requires elevated privileges (root/sudo)[/yellow]"
        )
        console.print(
            "[cyan]Low ports (< 1024) require administrator permissions on most systems[/cyan]"
        )

        # Check if suggested port is available
        suggested_available, _ = is_port_available(suggested_port)
        if suggested_available:
            console.print(
                f"\n[green]Suggested alternative: Use port {suggested_port} instead?[/green]"
            )
            console.print(
                f"[dim]This would forward: localhost:{suggested_port} -> service:{local_port}[/dim]"
            )

            response = (
                input("\nUse suggested port? [Y/n]: ").strip().lower() or "y"
            )  # Default to 'y' if empty

            if response in ["y", "yes"]:
                # Update port_forward_args in place
                _update_port_mapping(port_forward_args, local_port, suggested_port)
                console.print(
                    f"[green]Updated port mapping to {suggested_port}:{local_port}[/green]"
                )
                return True
            else:
                console.print("[yellow]Port change declined. Exiting.[/yellow]")
                return False
        else:
            console.print(f"[yellow]Suggested port {suggested_port} is also unavailable[/yellow]")
            console.print(
                "[yellow]Please choose a different port or run with elevated privileges (sudo)[/yellow]"
            )
            return False

    # Regular "port in use" error
    elif error_reason == "in_use":
        # Check if auto-select is enabled
        auto_select = config.get("autoSelectFreePort", True) if config else True

        if auto_select:
            next_port = find_next_free_port(local_port)
            if next_port:
                console.print(f"[yellow]Port {local_port} is in use[/yellow]")
                console.print(f"[green]Auto-selecting port {next_port}[/green]")
                # Update port_forward_args with new port
                _update_port_mapping(port_forward_args, local_port, next_port)
                if debug_callback:
                    debug_callback(f"Auto-selected port {next_port}")
                return True
            else:
                # Auto-select failed, fall through to error message
                console.print(f"[yellow]Port {local_port} is in use[/yellow]")
                console.print(
                    f"[yellow]Could not find an available port (tried {local_port}-{local_port + 9})[/yellow]"
                )
                return False

        # Auto-select disabled or not available - show error
        console.print(f"[red]Error: Local port {local_port} is already in use[/red]")
        console.print(
            f"[yellow]Please choose a different port or free up port {local_port}[/yellow]"
        )
        return False

    # Unknown error
    else:
        console.print(f"[red]Error: Local port {local_port} is not available[/red]")
        console.print(f"[yellow]Reason: {error_reason}[/yellow]")
        return False


def _update_port_mapping(port_forward_args, old_local_port, new_local_port):
    """Update the port mapping in port_forward_args list in place.

    Args:
        port_forward_args: List of arguments to modify
        old_local_port: The old local port to replace
        new_local_port: The new local port to use
    """
    for i, arg in enumerate(port_forward_args):
        if ":" in arg and not arg.startswith("-"):
            parts = arg.split(":", 1)
            try:
                if int(parts[0]) == old_local_port:
                    # Replace with new mapping
                    port_forward_args[i] = f"{new_local_port}:{parts[1]}"
                    return
            except ValueError:
                continue
