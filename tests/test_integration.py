"""Integration tests for kpf."""

import subprocess
import sys
from unittest.mock import Mock, patch

import pytest


class TestCLIIntegration:
    """Integration tests for CLI functionality."""

    def test_help_output(self):
        """Test that help output works."""
        result = subprocess.run(
            [sys.executable, "-m", "src.kpf.cli", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "kpf" in result.stdout
        assert "kubectl port-forward" in result.stdout.lower()
        assert "--prompt" in result.stdout
        assert "--check" in result.stdout

    def test_version_output(self):
        """Test that version output works."""
        result = subprocess.run(
            [sys.executable, "-m", "src.kpf.cli", "--version"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "kpf" in result.stdout
        assert "0.1.22" in result.stdout

    @patch("src.kpf.cli.handle_prompt_mode")
    @patch("src.kpf.cli.run_port_forward")
    @patch("sys.argv", ["kpf", "--prompt"])
    def test_prompt_mode_integration(self, mock_run_pf, mock_handle_prompt):
        """Test prompt mode integration."""
        mock_handle_prompt.return_value = ["svc/test", "8080:8080", "-n", "default"]

        # Import and call main directly instead of using subprocess
        from src.kpf.cli import main

        # Should not raise any exceptions
        main()

        # Verify the mocked functions were called
        mock_handle_prompt.assert_called_once()
        mock_run_pf.assert_called_once_with(
            ["svc/test", "8080:8080", "-n", "default"], debug_mode=False
        )

    def test_import_structure(self):
        """Test that all modules can be imported without errors."""
        try:
            from src.kpf import __version__
            from src.kpf.cli import main
            from src.kpf.display import ServiceSelector
            from src.kpf.kubernetes import KubernetesClient, ServiceInfo
            from src.kpf.main import run_port_forward

            assert __version__ == "0.1.22"
            assert callable(main)
            assert KubernetesClient is not None
            assert ServiceInfo is not None
            assert ServiceSelector is not None
            assert callable(run_port_forward)

        except ImportError as e:
            pytest.fail(f"Import error: {e}")


class TestEndToEndScenarios:
    """End-to-end scenario tests."""

    @patch("subprocess.run")
    def test_kubectl_not_available(self, mock_run):
        """Test behavior when kubectl is not available."""
        mock_run.side_effect = FileNotFoundError("kubectl not found")

        from src.kpf.display import ServiceSelector
        from src.kpf.kubernetes import KubernetesClient

        # KubernetesClient should work without kubectl check
        client = KubernetesClient()

        # ServiceSelector should fail when kubectl is not available
        with pytest.raises(RuntimeError, match="kubectl command not found"):
            ServiceSelector(client)

    @patch("subprocess.run")
    def test_kubectl_connection_error(self, mock_run):
        """Test behavior when kubectl can't connect to cluster."""

        # Mock kubectl version to succeed (command exists)
        # But cluster operations fail
        def mock_subprocess(*args, **kwargs):
            cmd = args[0]
            if "version" in cmd:
                result = Mock()
                result.returncode = 0
                return result
            else:
                # Simulate connection error for other commands
                raise subprocess.CalledProcessError(1, cmd, stderr=b"connection refused")

        mock_run.side_effect = mock_subprocess

        from src.kpf.kubernetes import KubernetesClient

        client = KubernetesClient()

        # Should handle connection errors gracefully
        with pytest.raises(RuntimeError, match="Failed to get namespaces"):
            client.get_all_namespaces()

    def test_port_availability_integration(self):
        """Test port availability checking in realistic scenario."""
        import socket

        from src.kpf.display import ServiceSelector

        # Create a real client (will fail kubectl check, but that's ok for this test)
        client = Mock()

        with patch.object(ServiceSelector, "_check_kubectl"):
            selector = ServiceSelector(client)

        # Test with a port that should be available
        high_port = 19999
        assert selector._is_port_available(high_port) is True

        # Test finding available port
        available = selector._find_available_port(high_port)
        assert available >= high_port
        assert selector._is_port_available(available) is True

        # Test with a bound port
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.bind(("localhost", high_port))
            assert selector._is_port_available(high_port) is False

            # Should find next available port
            next_available = selector._find_available_port(high_port + 1)
            assert next_available > high_port
            assert selector._is_port_available(next_available) is True

        finally:
            test_socket.close()


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_invalid_service_resource(self):
        """Test handling of invalid service resource format."""
        from src.kpf.main import get_watcher_args

        # Invalid resource format should exit
        with patch("sys.exit") as mock_exit:
            get_watcher_args(["invalid-resource", "8080:8080"])
            mock_exit.assert_called_once_with(1)

    def test_malformed_kubectl_output(self):
        """Test handling of malformed kubectl JSON output."""
        from src.kpf.kubernetes import KubernetesClient

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "invalid json"
            mock_run.return_value.returncode = 0

            client = KubernetesClient()

            with pytest.raises(RuntimeError, match="Failed to parse services JSON"):
                client.get_services_in_namespace("default")

    def test_empty_services_response(self):
        """Test handling of empty services response."""
        from src.kpf.kubernetes import KubernetesClient

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = '{"items": []}'
            mock_run.return_value.returncode = 0

            client = KubernetesClient()
            services = client.get_services_in_namespace("empty-namespace")

            assert services == []

    def test_service_without_endpoints_command(self):
        """Test the specific service without endpoints command that causes infinite loop."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.kpf.cli",
                "-n",
                "test-namespace",
                "svc/fake",
                "17071:17071",
            ],
            capture_output=True,
            text=True,
            timeout=15,  # Should fail fast, not timeout
        )

        assert result.returncode == 1
        assert "not found" in result.stdout.lower()
        # Should not contain looping messages
        loop_count = result.stdout.count("Starting watcher for endpoint changes")
        assert loop_count <= 1  # At most one attempt, not continuous looping
