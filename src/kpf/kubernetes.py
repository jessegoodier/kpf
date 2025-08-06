#!/usr/bin/env python3

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ServiceInfo:
    """Information about a Kubernetes service."""

    name: str
    namespace: str
    ports: List[Dict[str, Any]]
    has_endpoints: bool
    service_type: str = "service"

    @property
    def display_name(self) -> str:
        """Return the display name for the service."""
        return f"svc/{self.name}"

    @property
    def port_summary(self) -> str:
        """Return a summary of available ports."""
        if not self.ports:
            return "No ports"

        port_strs = []
        for port in self.ports:
            if "port" in port:
                port_str = str(port["port"])
                if "targetPort" in port and port["targetPort"] != port["port"]:
                    port_str += f"->{port['targetPort']}"
                if "name" in port and port["name"]:
                    port_str += f" ({port['name']})"
                port_strs.append(port_str)

        return ", ".join(port_strs)


class KubernetesClient:
    """Client for interacting with Kubernetes via kubectl."""

    # def __init__(self):
    #     self._check_kubectl()

    # def _check_kubectl(self):
    #     """Check if kubectl is available."""
    #     try:
    #         subprocess.run(["kubectl", "version"], capture_output=True, check=True)
    #     except (subprocess.CalledProcessError, FileNotFoundError):
    #         raise RuntimeError("kubectl is not available or not configured properly")

    def get_current_namespace(self) -> str:
        """Get the current namespace from kubectl context."""
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "config",
                    "view",
                    "--minify",
                    "-o",
                    "jsonpath={..namespace}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            namespace = result.stdout.strip()
            return namespace if namespace else "default"
        except subprocess.CalledProcessError:
            return "default"

    def get_all_namespaces(self) -> List[str]:
        """Get all available namespaces."""
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "namespaces",
                    "-o",
                    "jsonpath={.items[*].metadata.name}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip().split()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get namespaces: {e}")

    def get_services_in_namespace(
        self, namespace: str, check_endpoints: bool = True
    ) -> List[ServiceInfo]:
        """Get all services in a specific namespace."""
        try:
            # Get services
            result = subprocess.run(
                ["kubectl", "get", "services", "-n", namespace, "-o", "json"],
                capture_output=True,
                text=True,
                check=True,
            )
            services_data = json.loads(result.stdout)

            services = []
            for item in services_data.get("items", []):
                service_name = item["metadata"]["name"]
                ports = item["spec"].get("ports", [])

                # Check if service has endpoints (only if requested)
                has_endpoints = (
                    self._service_has_endpoints(namespace, service_name)
                    if check_endpoints
                    else False
                )

                services.append(
                    ServiceInfo(
                        name=service_name,
                        namespace=namespace,
                        ports=ports,
                        has_endpoints=has_endpoints,
                        service_type="service",
                    )
                )

            return sorted(services, key=lambda s: s.name)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get services in namespace {namespace}: {e}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse services JSON: {e}")

    def get_all_services(self, check_endpoints: bool = True) -> Dict[str, List[ServiceInfo]]:
        """Get all services across all namespaces."""
        try:
            namespaces = self.get_all_namespaces()
            all_services = {}

            for namespace in namespaces:
                try:
                    services = self.get_services_in_namespace(namespace, check_endpoints)
                    if services:  # Only include namespaces with services
                        all_services[namespace] = services
                except RuntimeError:
                    # Skip namespaces we can't access
                    continue

            return all_services

        except RuntimeError as e:
            raise RuntimeError(f"Failed to get all services: {e}")

    def _service_has_endpoints(self, namespace: str, service_name: str) -> bool:
        """Check if a service has endpoints."""
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "endpoints",
                    service_name,
                    "-n",
                    namespace,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,  # Don't raise on non-zero exit
            )

            if result.returncode != 0:
                return False

            endpoints_data = json.loads(result.stdout)
            subsets = endpoints_data.get("subsets", [])

            # Check if any subset has addresses
            for subset in subsets:
                if subset.get("addresses"):
                    return True

            return False

        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return False

    def get_pods_with_ports(self, namespace: str) -> List[ServiceInfo]:
        """Get pods with exposed ports in a namespace."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
                capture_output=True,
                text=True,
                check=True,
            )
            pods_data = json.loads(result.stdout)

            pods_with_ports = []
            for item in pods_data.get("items", []):
                pod_name = item["metadata"]["name"]
                containers = item["spec"].get("containers", [])

                # Collect all container ports
                all_ports = []
                for container in containers:
                    ports = container.get("ports", [])
                    for port in ports:
                        all_ports.append(
                            {
                                "port": port.get("containerPort"),
                                "protocol": port.get("protocol", "TCP"),
                                "name": port.get("name", ""),
                            }
                        )

                if all_ports:
                    pods_with_ports.append(
                        ServiceInfo(
                            name=pod_name,
                            namespace=namespace,
                            ports=all_ports,
                            has_endpoints=True,  # Pods are their own endpoints
                            service_type="pod",
                        )
                    )

            return sorted(pods_with_ports, key=lambda p: p.name)

        except (subprocess.CalledProcessError, json.JSONDecodeError):
            # Return empty list if we can't get pods
            return []

    def get_deployments_with_ports(self, namespace: str) -> List[ServiceInfo]:
        """Get deployments with exposed ports in a namespace."""
        try:
            result = subprocess.run(
                ["kubectl", "get", "deployments", "-n", namespace, "-o", "json"],
                capture_output=True,
                text=True,
                check=True,
            )
            deployments_data = json.loads(result.stdout)

            deployments_with_ports = []
            for item in deployments_data.get("items", []):
                deployment_name = item["metadata"]["name"]
                containers = item["spec"]["template"]["spec"].get("containers", [])

                # Collect all container ports
                all_ports = []
                for container in containers:
                    ports = container.get("ports", [])
                    for port in ports:
                        all_ports.append(
                            {
                                "port": port.get("containerPort"),
                                "protocol": port.get("protocol", "TCP"),
                                "name": port.get("name", ""),
                            }
                        )

                if all_ports:
                    deployments_with_ports.append(
                        ServiceInfo(
                            name=deployment_name,
                            namespace=namespace,
                            ports=all_ports,
                            has_endpoints=True,  # Assume deployments have endpoints
                            service_type="deployment",
                        )
                    )

            return sorted(deployments_with_ports, key=lambda d: d.name)

        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            # Return empty list if we can't get deployments
            return []
