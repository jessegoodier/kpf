#!/usr/bin/env python3

import sys
from typing import List, Optional, Dict
from rich.console import Console
from rich.table import Table
from rich.prompt import IntPrompt

from .kubernetes import KubernetesClient, ServiceInfo


class ServiceSelector:
    """Interactive service selector with colored output."""
    
    def __init__(self, k8s_client: KubernetesClient):
        self.k8s_client = k8s_client
        self.console = Console()
    
    def select_service_in_namespace(self, namespace: Optional[str] = None, include_all_ports: bool = False) -> List[str]:
        """Select a service interactively within a specific namespace."""
        if not namespace:
            namespace = self.k8s_client.get_current_namespace()
        
        self.console.print(f"\n[bold blue]Services in namespace: {namespace}[/bold blue]")
        
        # Get services
        services = self.k8s_client.get_services_in_namespace(namespace)
        
        # Optionally include pods and deployments
        all_resources = services.copy()
        if include_all_ports:
            pods = self.k8s_client.get_pods_with_ports(namespace)
            deployments = self.k8s_client.get_deployments_with_ports(namespace)
            all_resources.extend(pods)
            all_resources.extend(deployments)
            all_resources.sort(key=lambda r: (r.service_type, r.name))
        
        if not all_resources:
            self.console.print(f"[yellow]No resources found in namespace '{namespace}'[/yellow]")
            return []
        
        # Display table
        self._display_services_table(all_resources)
        
        # Get user selection
        return self._prompt_for_service_selection(all_resources, namespace)
    
    def select_service_all_namespaces(self, include_all_ports: bool = False) -> List[str]:
        """Select a service interactively across all namespaces."""
        self.console.print("\n[bold blue]Services across all namespaces[/bold blue]")
        
        # Get all services
        all_services_by_ns = self.k8s_client.get_all_services()
        
        if not all_services_by_ns:
            self.console.print("[yellow]No services found in any namespace[/yellow]")
            return []
        
        # Flatten and add pods/deployments if requested
        all_resources = []
        for namespace, services in all_services_by_ns.items():
            all_resources.extend(services)
            
            if include_all_ports:
                pods = self.k8s_client.get_pods_with_ports(namespace)
                deployments = self.k8s_client.get_deployments_with_ports(namespace)
                all_resources.extend(pods)
                all_resources.extend(deployments)
        
        # Sort by namespace, then type, then name
        all_resources.sort(key=lambda r: (r.namespace, r.service_type, r.name))
        
        # Display table
        self._display_services_table(all_resources, show_namespace=True)
        
        # Get user selection
        return self._prompt_for_service_selection(all_resources)
    
    def _display_services_table(self, resources: List[ServiceInfo], show_namespace: bool = False):
        """Display services in a colored table."""
        table = Table()
        
        table.add_column("#", style="dim", width=4)
        if show_namespace:
            table.add_column("Namespace", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Name", style="bold")
        table.add_column("Ports", style="blue")
        table.add_column("Status", justify="center")
        
        for i, resource in enumerate(resources, 1):
            # Color coding based on endpoint status
            status_color = "green" if resource.has_endpoints else "red"
            status_text = "✓" if resource.has_endpoints else "✗"
            
            row = [
                str(i),
                resource.service_type.upper(),
                resource.name,
                resource.port_summary,
                f"[{status_color}]{status_text}[/{status_color}]"
            ]
            
            if show_namespace:
                row.insert(1, resource.namespace)
            
            table.add_row(*row)
        
        self.console.print(table)
        
        # Legend
        self.console.print("\n[green]✓[/green] = Has endpoints  [red]✗[/red] = No endpoints")
    
    def _prompt_for_service_selection(self, resources: List[ServiceInfo], namespace: Optional[str] = None) -> List[str]:
        """Prompt user to select a service and return port-forward arguments."""
        try:
            selection = IntPrompt.ask(
                "\nSelect a service",
                default=1,
                show_default=True
            )
            
            if selection < 1 or selection > len(resources):
                self.console.print("[red]Invalid selection[/red]")
                return []
            
            selected_resource = resources[selection - 1]
            
            # If no ports available, can't port-forward
            if not selected_resource.ports:
                self.console.print(f"[red]Service '{selected_resource.name}' has no ports defined[/red]")
                return []
            
            # If only one port, use it directly
            if len(selected_resource.ports) == 1:
                port = selected_resource.ports[0]["port"]
                local_port = self._prompt_for_local_port(port)
                
                args = [
                    f"{selected_resource.service_type}/{selected_resource.name}",
                    f"{local_port}:{port}",
                    "-n", selected_resource.namespace
                ]
                return args
            
            # Multiple ports - let user choose
            return self._prompt_for_port_selection(selected_resource)
            
        except KeyboardInterrupt:
            return []
    
    def _prompt_for_port_selection(self, resource: ServiceInfo) -> List[str]:
        """Prompt user to select a port when multiple are available."""
        self.console.print(f"\n[bold]Available ports for {resource.name}:[/bold]")
        
        port_table = Table()
        port_table.add_column("#", style="dim", width=4)
        port_table.add_column("Port", style="bold")
        port_table.add_column("Protocol", style="blue")
        port_table.add_column("Name", style="green")
        
        for i, port in enumerate(resource.ports, 1):
            port_table.add_row(
                str(i),
                str(port["port"]),
                port.get("protocol", "TCP"),
                port.get("name", "")
            )
        
        self.console.print(port_table)
        
        try:
            port_selection = IntPrompt.ask(
                "Select a port",
                default=1,
                show_default=True
            )
            
            if port_selection < 1 or port_selection > len(resource.ports):
                self.console.print("[red]Invalid port selection[/red]")
                return []
            
            selected_port = resource.ports[port_selection - 1]["port"]
            local_port = self._prompt_for_local_port(selected_port)
            
            args = [
                f"{resource.service_type}/{resource.name}",
                f"{local_port}:{selected_port}",
                "-n", resource.namespace
            ]
            return args
            
        except KeyboardInterrupt:
            return []
    
    def _prompt_for_local_port(self, remote_port: int) -> int:
        """Prompt user for local port, defaulting to remote port."""
        try:
            local_port = IntPrompt.ask(
                f"Local port (press Enter for {remote_port})",
                default=remote_port,
                show_default=False
            )
            return local_port
        except KeyboardInterrupt:
            return remote_port