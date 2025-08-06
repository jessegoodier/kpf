"""Tests for kubernetes module."""

import json
import subprocess
from unittest.mock import patch

from src.kpf.kubernetes import KubernetesClient, ServiceInfo


class TestServiceInfo:
    """Test ServiceInfo dataclass."""

    def test_service_info_creation(self, sample_service_info):
        """Test ServiceInfo object creation."""
        assert sample_service_info.name == "test-service"
        assert sample_service_info.namespace == "default"
        assert len(sample_service_info.ports) == 2
        assert sample_service_info.has_endpoints is True
        assert sample_service_info.service_type == "service"

    def test_display_name_property(self, sample_service_info, sample_pod_info):
        """Test display_name property for different service types."""
        assert sample_service_info.display_name == "svc/test-service"
        assert sample_pod_info.display_name == "svc/test-pod"  # Always returns svc/ prefix

    def test_port_summary_with_ports(self, sample_service_info):
        """Test port_summary with multiple ports."""
        summary = sample_service_info.port_summary
        assert "80->8080 (http)" in summary
        assert "443->8443 (https)" in summary
        assert "," in summary

    def test_port_summary_simple_port(self):
        """Test port_summary with simple port (no targetPort or name)."""
        service = ServiceInfo(
            name="simple-service",
            namespace="default",
            ports=[{"port": 8080, "protocol": "TCP"}],
            has_endpoints=True,
            service_type="service",
        )
        assert service.port_summary == "8080"

    def test_port_summary_no_ports(self):
        """Test port_summary with no ports."""
        service = ServiceInfo(
            name="no-ports-service",
            namespace="default",
            ports=[],
            has_endpoints=False,
            service_type="service",
        )
        assert service.port_summary == "No ports"

    def test_port_summary_same_target_port(self):
        """Test port_summary when port and targetPort are the same."""
        service = ServiceInfo(
            name="same-port-service",
            namespace="default",
            ports=[{"port": 8080, "targetPort": 8080, "protocol": "TCP", "name": "web"}],
            has_endpoints=True,
            service_type="service",
        )
        # Should not show ->8080 since it's the same
        assert service.port_summary == "8080 (web)"


class TestKubernetesClient:
    """Test KubernetesClient class."""

    @patch("subprocess.run")
    def test_get_current_namespace_with_namespace(self, mock_run):
        """Test getting current namespace when one is set."""
        mock_run.return_value.stdout = "production"
        mock_run.return_value.returncode = 0

        client = KubernetesClient()
        namespace = client.get_current_namespace()

        assert namespace == "production"
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_current_namespace_default(self, mock_run):
        """Test getting current namespace when none is set."""
        mock_run.return_value.stdout = ""
        mock_run.return_value.returncode = 0

        client = KubernetesClient()
        namespace = client.get_current_namespace()

        assert namespace == "default"

    @patch("subprocess.run")
    def test_get_current_namespace_error(self, mock_run):
        """Test getting current namespace when kubectl fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["kubectl"])

        client = KubernetesClient()
        namespace = client.get_current_namespace()

        assert namespace == "default"

    @patch("subprocess.run")
    def test_get_all_namespaces(self, mock_run):
        """Test getting all namespaces."""
        mock_run.return_value.stdout = "default kube-system production"
        mock_run.return_value.returncode = 0

        client = KubernetesClient()
        namespaces = client.get_all_namespaces()

        assert namespaces == ["default", "kube-system", "production"]

    @patch("subprocess.run")
    def test_get_services_in_namespace(self, mock_run):
        """Test getting services in a namespace."""
        services_json = {
            "items": [
                {
                    "metadata": {"name": "test-service"},
                    "spec": {"ports": [{"port": 80, "targetPort": 8080}]},
                }
            ]
        }
        mock_run.return_value.stdout = json.dumps(services_json)
        mock_run.return_value.returncode = 0

        client = KubernetesClient()

        # Mock the endpoint checking method
        with patch.object(client, "_service_has_endpoints", return_value=True):
            services = client.get_services_in_namespace("default", check_endpoints=True)

        assert len(services) == 1
        assert services[0].name == "test-service"
        assert services[0].has_endpoints is True

    @patch("subprocess.run")
    def test_get_services_without_endpoint_check(self, mock_run):
        """Test getting services without checking endpoints."""
        services_json = {
            "items": [{"metadata": {"name": "test-service"}, "spec": {"ports": [{"port": 80}]}}]
        }
        mock_run.return_value.stdout = json.dumps(services_json)
        mock_run.return_value.returncode = 0

        client = KubernetesClient()
        services = client.get_services_in_namespace("default", check_endpoints=False)

        assert len(services) == 1
        assert services[0].name == "test-service"
        assert services[0].has_endpoints is False  # Should be False when not checked

    @patch("subprocess.run")
    def test_service_has_endpoints_true(self, mock_run):
        """Test _service_has_endpoints when endpoints exist."""
        endpoints_json = {"subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]}
        mock_run.return_value.stdout = json.dumps(endpoints_json)
        mock_run.return_value.returncode = 0

        client = KubernetesClient()
        has_endpoints = client._service_has_endpoints("default", "test-service")

        assert has_endpoints is True

    @patch("subprocess.run")
    def test_service_has_endpoints_false(self, mock_run):
        """Test _service_has_endpoints when no endpoints exist."""
        endpoints_json = {"subsets": []}
        mock_run.return_value.stdout = json.dumps(endpoints_json)
        mock_run.return_value.returncode = 0

        client = KubernetesClient()
        has_endpoints = client._service_has_endpoints("default", "test-service")

        assert has_endpoints is False

    @patch("subprocess.run")
    def test_service_has_endpoints_error(self, mock_run):
        """Test _service_has_endpoints when kubectl fails."""
        mock_run.return_value.returncode = 1

        client = KubernetesClient()
        has_endpoints = client._service_has_endpoints("default", "test-service")

        assert has_endpoints is False

    @patch("subprocess.run")
    def test_get_pods_with_ports(self, mock_run):
        """Test getting pods with ports."""
        pods_json = {
            "items": [
                {
                    "metadata": {"name": "test-pod"},
                    "spec": {
                        "containers": [
                            {"ports": [{"containerPort": 3000, "protocol": "TCP", "name": "app"}]}
                        ]
                    },
                }
            ]
        }
        mock_run.return_value.stdout = json.dumps(pods_json)
        mock_run.return_value.returncode = 0

        client = KubernetesClient()
        pods = client.get_pods_with_ports("default")

        assert len(pods) == 1
        assert pods[0].name == "test-pod"
        assert pods[0].service_type == "pod"
        assert pods[0].has_endpoints is True  # Pods are their own endpoints

    @patch("subprocess.run")
    def test_get_deployments_with_ports(self, mock_run):
        """Test getting deployments with ports."""
        deployments_json = {
            "items": [
                {
                    "metadata": {"name": "test-deployment"},
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {"ports": [{"containerPort": 8080, "protocol": "TCP"}]}
                                ]
                            }
                        }
                    },
                }
            ]
        }
        mock_run.return_value.stdout = json.dumps(deployments_json)
        mock_run.return_value.returncode = 0

        client = KubernetesClient()
        deployments = client.get_deployments_with_ports("default")

        assert len(deployments) == 1
        assert deployments[0].name == "test-deployment"
        assert deployments[0].service_type == "deployment"
        assert deployments[0].has_endpoints is True  # Assume deployments have endpoints
