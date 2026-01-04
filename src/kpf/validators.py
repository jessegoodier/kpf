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


def is_port_available(port: int) -> bool:
    """Check if a port is available on localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("localhost", port))
            return True
    except OSError:
        return False


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


def validate_port_availability(port_forward_args, debug_callback=None):
    """Validate that the local port in port-forward args is available."""
    local_port = extract_local_port(port_forward_args)
    if local_port is None:
        if debug_callback:
            debug_callback("Could not extract local port from arguments")
        return True  # Can't validate, let kubectl handle it

    if not is_port_available(local_port):
        console.print(f"[red]Error: Local port {local_port} is already in use[/red]")
        console.print(
            f"[yellow]Please choose a different port or free up port {local_port}[/yellow]"
        )
        return False

    if debug_callback:
        debug_callback(f"[green]Port {local_port} is available[/green]")
    return True
