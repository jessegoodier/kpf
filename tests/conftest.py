"""Pytest configuration and fixtures."""

import pytest
from unittest.mock import Mock, MagicMock
from src.kpf.kubernetes import ServiceInfo, KubernetesClient


@pytest.fixture
def sample_service_info():
    """Sample ServiceInfo object for testing."""
    return ServiceInfo(
        name="test-service",
        namespace="default",
        ports=[
            {"port": 80, "targetPort": 8080, "protocol": "TCP", "name": "http"},
            {"port": 443, "targetPort": 8443, "protocol": "TCP", "name": "https"}
        ],
        has_endpoints=True,
        service_type="service"
    )


@pytest.fixture
def sample_service_no_endpoints():
    """Sample ServiceInfo object without endpoints."""
    return ServiceInfo(
        name="broken-service",
        namespace="default",
        ports=[{"port": 8080, "protocol": "TCP"}],
        has_endpoints=False,
        service_type="service"
    )


@pytest.fixture
def sample_pod_info():
    """Sample pod ServiceInfo object for testing."""
    return ServiceInfo(
        name="test-pod",
        namespace="default",
        ports=[{"port": 3000, "protocol": "TCP", "name": "app"}],
        has_endpoints=True,
        service_type="pod"
    )


@pytest.fixture
def mock_kubectl_client():
    """Mock KubernetesClient for testing."""
    client = Mock(spec=KubernetesClient)
    client.get_current_namespace.return_value = "default"
    client.get_all_namespaces.return_value = ["default", "kube-system", "production"]
    return client


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for testing kubectl calls."""
    with pytest.mock.patch("subprocess.run") as mock_run:
        mock_result = Mock()
        mock_result.stdout = '{"items": []}'
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        yield mock_run