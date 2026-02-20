"""Tests for display module."""

import socket
import subprocess
from unittest.mock import Mock, patch

import pytest

from src.kpf.display import ServiceSelector
from src.kpf.kubernetes import ServiceInfo


class TestServiceSelector:
    """Test ServiceSelector class."""

    @pytest.mark.parametrize(
        ("typed_number", "digit", "max_index", "current_index", "expected"),
        [
            ("", "3", 9, 1, ("3", 3, True)),
            ("1", "2", 9, 1, ("2", 2, True)),
            ("1", "2", 12, 1, ("12", 12, True)),
            ("12", "3", 50, 12, ("23", 23, True)),
            ("", "0", 9, 4, ("", 4, False)),
        ],
    )
    def test_apply_typed_digit(self, typed_number, digit, max_index, current_index, expected):
        """Test numeric typing buffer behavior for interactive selectors."""
        assert (
            ServiceSelector._apply_typed_digit(typed_number, digit, max_index, current_index)
            == expected
        )

    @pytest.fixture
    def mock_k8s_client(self):
        """Mock KubernetesClient for ServiceSelector."""
        client = Mock()
        client.get_current_namespace.return_value = "default"
        return client

    @pytest.fixture
    def service_selector(self, mock_k8s_client):
        """ServiceSelector instance with mocked kubectl check."""
        with patch.object(ServiceSelector, "_check_kubectl"):
            return ServiceSelector(mock_k8s_client)

    def test_is_port_available_free_port(self, service_selector):
        """Test _is_port_available with a free port."""
        # Use a high port number that's likely to be free
        test_port = 19999
        result = service_selector._is_port_available(test_port)
        assert result is True

    def test_is_port_available_bound_port(self, service_selector):
        """Test _is_port_available with a port that's in use."""
        test_port = 19998

        # Bind to the port first
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.bind(("localhost", test_port))

            # Now test that it's detected as unavailable
            result = service_selector._is_port_available(test_port)
            assert result is False

        finally:
            test_socket.close()

    def test_find_available_port(self, service_selector):
        """Test _find_available_port functionality."""
        # Start with a high port number
        starting_port = 19990

        available_port = service_selector._find_available_port(starting_port)

        # Should return a port >= starting_port
        assert available_port >= starting_port
        # Should be available
        assert service_selector._is_port_available(available_port) is True

    def test_find_available_port_with_occupied_ports(self, service_selector):
        """Test _find_available_port when several ports are occupied."""
        starting_port = 19980
        sockets = []

        try:
            # Bind to first 3 ports
            for i in range(3):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("localhost", starting_port + i))
                sockets.append(sock)

            # Should find the 4th port (starting_port + 3)
            available_port = service_selector._find_available_port(starting_port)
            assert available_port == starting_port + 3

        finally:
            for sock in sockets:
                sock.close()

    def test_find_available_port_all_occupied(self, service_selector):
        """Test _find_available_port when all ports in range are occupied."""
        starting_port = 19970
        max_attempts = 3
        sockets = []

        try:
            # Bind to all ports in the range
            for i in range(max_attempts):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("localhost", starting_port + i))
                sockets.append(sock)

            # Should return the starting port when no free port is found
            available_port = service_selector._find_available_port(starting_port, max_attempts)
            assert available_port == starting_port

        finally:
            for sock in sockets:
                sock.close()

    @patch("rich.prompt.IntPrompt.ask")
    def test_prompt_for_local_port_available(self, mock_prompt, service_selector):
        """Test _prompt_for_local_port when port is available."""
        remote_port = 8080
        mock_prompt.return_value = remote_port

        with patch.object(service_selector, "_is_port_available", return_value=True):
            result = service_selector._prompt_for_local_port(remote_port)

        assert result == remote_port
        mock_prompt.assert_called_once()
        # Should prompt with the remote port as default
        args, kwargs = mock_prompt.call_args
        assert str(remote_port) in args[0]
        assert kwargs["default"] == remote_port

    @patch("rich.prompt.IntPrompt.ask")
    def test_prompt_for_local_port_unavailable(self, mock_prompt, service_selector):
        """Test _prompt_for_local_port when port is unavailable."""
        remote_port = 8080
        suggested_port = 8081
        mock_prompt.return_value = suggested_port

        with (
            patch.object(service_selector, "_is_port_available", return_value=False),
            patch.object(service_selector, "_find_available_port", return_value=suggested_port),
        ):
            result = service_selector._prompt_for_local_port(remote_port)

        assert result == suggested_port
        mock_prompt.assert_called_once()
        # Should prompt with the suggested port as default
        args, kwargs = mock_prompt.call_args
        assert str(suggested_port) in args[0]
        assert kwargs["default"] == suggested_port

    @patch("rich.prompt.IntPrompt.ask")
    def test_prompt_for_local_port_custom_unavailable(self, mock_prompt, service_selector):
        """Test _prompt_for_local_port when user enters unavailable port."""
        remote_port = 8080
        user_port = 3000
        mock_prompt.return_value = user_port

        # Mock port availability: 8080 available, 3000 not available
        def mock_port_available(port):
            return port != user_port

        with (
            patch.object(service_selector, "_is_port_available", side_effect=mock_port_available),
            patch.object(service_selector, "_find_available_port", return_value=8081),
            patch.object(service_selector.console, "print") as mock_print,
        ):
            result = service_selector._prompt_for_local_port(remote_port)

        assert result == user_port
        # Should print warning about port being in use
        mock_print.assert_called()
        warning_call = [call for call in mock_print.call_args_list if "Warning" in str(call)]
        assert len(warning_call) > 0

    @patch("rich.prompt.IntPrompt.ask")
    def test_prompt_for_local_port_privileged_available(self, mock_prompt, service_selector):
        """Test _prompt_for_local_port with privileged port (< 1024) that is available after adding 1000."""
        remote_port = 80  # HTTP port (privileged)
        suggested_port = 1080  # 80 + 1000
        user_port = 1080
        mock_prompt.return_value = user_port

        def mock_port_available(port):
            return port == suggested_port  # Only 1080 is available

        with (
            patch.object(service_selector, "_is_port_available", side_effect=mock_port_available),
            patch.object(service_selector.console, "print") as mock_print,
        ):
            result = service_selector._prompt_for_local_port(remote_port)

        assert result == user_port
        # Should print privileged port message
        privileged_calls = [call for call in mock_print.call_args_list if "privileged" in str(call)]
        assert len(privileged_calls) > 0
        # Should suggest 1080
        suggested_calls = [call for call in mock_print.call_args_list if "1080" in str(call)]
        assert len(suggested_calls) > 0

    @patch("rich.prompt.IntPrompt.ask")
    def test_prompt_for_local_port_privileged_unavailable(self, mock_prompt, service_selector):
        """Test _prompt_for_local_port with privileged port when suggested port (port+1000) is in use."""
        remote_port = 443  # HTTPS port (privileged)
        alternative_port = 1444  # Next available
        user_port = 1444
        mock_prompt.return_value = user_port

        def mock_port_available(port):
            return port == alternative_port  # Only 1444 is available

        with (
            patch.object(service_selector, "_is_port_available", side_effect=mock_port_available),
            patch.object(service_selector, "_find_available_port", return_value=alternative_port),
            patch.object(service_selector.console, "print") as mock_print,
        ):
            result = service_selector._prompt_for_local_port(remote_port)

        assert result == user_port
        # Should print privileged port message
        privileged_calls = [call for call in mock_print.call_args_list if "privileged" in str(call)]
        assert len(privileged_calls) > 0
        # Should print that 1443 is in use
        unavailable_calls = [
            call
            for call in mock_print.call_args_list
            if "1443" in str(call) and "already in use" in str(call)
        ]
        assert len(unavailable_calls) > 0

    @patch("rich.prompt.IntPrompt.ask")
    def test_prompt_for_local_port_non_privileged(self, mock_prompt, service_selector):
        """Test _prompt_for_local_port with non-privileged port (>= 1024) uses existing behavior."""
        remote_port = 8080  # Non-privileged port
        user_port = 8080
        mock_prompt.return_value = user_port

        def mock_port_available(port):
            return port == remote_port  # Port is available

        with (
            patch.object(service_selector, "_is_port_available", side_effect=mock_port_available),
            patch.object(service_selector.console, "print") as mock_print,
        ):
            result = service_selector._prompt_for_local_port(remote_port)

        assert result == user_port
        # Should NOT print privileged port message
        privileged_calls = [call for call in mock_print.call_args_list if "privileged" in str(call)]
        assert len(privileged_calls) == 0

    def test_display_services_table_without_check(self, service_selector, sample_service_info):
        """Test _display_services_table without endpoint checking."""
        services = [sample_service_info]

        with patch.object(service_selector.console, "print") as mock_print:
            service_selector._display_services_table(services, check_endpoints=False)

        # Should print table without status column
        mock_print.assert_called()
        # Should not print legend
        legend_calls = [call for call in mock_print.call_args_list if "✓" in str(call)]
        assert len(legend_calls) == 0

    def test_display_services_table_with_check(self, service_selector, sample_service_info):
        """Test _display_services_table with endpoint checking."""
        services = [sample_service_info]

        with patch.object(service_selector.console, "print") as mock_print:
            service_selector._display_services_table(services, check_endpoints=True)

        # Should print table and legend
        mock_print.assert_called()
        # Should print legend
        legend_calls = [call for call in mock_print.call_args_list if "✓" in str(call)]
        assert len(legend_calls) > 0

    def test_check_kubectl_success(self, mock_k8s_client):
        """Test _check_kubectl when kubectl is available."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            # Should not raise an exception
            selector = ServiceSelector(mock_k8s_client)
            assert selector is not None

    def test_check_kubectl_not_found(self, mock_k8s_client):
        """Test _check_kubectl when kubectl is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="kubectl command not found"):
                ServiceSelector(mock_k8s_client)

    def test_check_kubectl_failed(self, mock_k8s_client):
        """Test _check_kubectl when kubectl command fails."""
        with patch("subprocess.run") as mock_run:
            # Create a proper CalledProcessError
            error = subprocess.CalledProcessError(1, ["kubectl", "version"])
            error.stderr = b"Connection refused"
            error.stdout = b""
            mock_run.side_effect = error

            with pytest.raises(RuntimeError, match="kubectl command failed"):
                ServiceSelector(mock_k8s_client)


class TestServiceSelectorIntegration:
    """Integration tests for ServiceSelector."""

    @pytest.fixture
    def mock_k8s_client_with_services(self):
        """Mock KubernetesClient with sample services."""
        client = Mock()
        client.get_current_namespace.return_value = "default"

        services = [
            ServiceInfo(
                name="web-service",
                namespace="default",
                ports=[{"port": 80, "protocol": "TCP"}],
                has_endpoints=True,
                service_type="service",
            ),
            ServiceInfo(
                name="api-service",
                namespace="default",
                ports=[{"port": 8080, "protocol": "TCP"}],
                has_endpoints=False,
                service_type="service",
            ),
        ]

        client.get_services_in_namespace.return_value = services
        client.get_pods_with_ports.return_value = []
        client.get_deployments_with_ports.return_value = []

        return client

    def test_select_service_in_namespace_no_resources(self, mock_k8s_client_with_services):
        """Test select_service_in_namespace when no resources found."""
        # Override the fixture to return empty results
        mock_k8s_client_with_services.get_services_in_namespace.return_value = []
        mock_k8s_client_with_services.get_pods_with_ports.return_value = []
        mock_k8s_client_with_services.get_deployments_with_ports.return_value = []

        with (
            patch.object(ServiceSelector, "_check_kubectl"),
            patch.object(ServiceSelector, "_display_services_table"),
            patch("rich.console.Console.print") as mock_print,
        ):
            selector = ServiceSelector(mock_k8s_client_with_services)
            result = selector.select_service_in_namespace("empty-namespace")

        assert result == []
        # Should print "No resources found" message
        no_resources_calls = [
            call for call in mock_print.call_args_list if "No resources found" in str(call)
        ]
        assert len(no_resources_calls) > 0

    def test_select_namespace_basic(self, mock_k8s_client_with_services):
        """Test select_namespace with namespaces available."""
        mock_k8s_client_with_services.get_all_namespaces.return_value = ["default", "kube-system"]

        with (
            patch.object(ServiceSelector, "_check_kubectl"),
            patch.object(
                ServiceSelector, "_prompt_for_namespace_selection", return_value="default"
            ),
        ):
            selector = ServiceSelector(mock_k8s_client_with_services)
            result = selector.select_namespace()

        assert result == "default"

    def test_select_namespace_empty(self, mock_k8s_client_with_services):
        """Test select_namespace when no namespaces found."""
        mock_k8s_client_with_services.get_all_namespaces.return_value = []

        with (
            patch.object(ServiceSelector, "_check_kubectl"),
            patch("rich.console.Console.print") as mock_print,
        ):
            selector = ServiceSelector(mock_k8s_client_with_services)
            result = selector.select_namespace()

        assert result is None
        mock_print.assert_called()
        no_ns_calls = [
            call for call in mock_print.call_args_list if "No namespaces found" in str(call)
        ]
        assert len(no_ns_calls) > 0

    def test_select_namespace_cancelled(self, mock_k8s_client_with_services):
        """Test select_namespace when cancelled."""
        mock_k8s_client_with_services.get_all_namespaces.return_value = ["default"]

        with (
            patch.object(ServiceSelector, "_check_kubectl"),
            patch.object(ServiceSelector, "_prompt_for_namespace_selection", return_value=None),
        ):
            selector = ServiceSelector(mock_k8s_client_with_services)
            result = selector.select_namespace()

        assert result is None
