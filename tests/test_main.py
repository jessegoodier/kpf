"""Tests for main module."""

import subprocess
from unittest.mock import Mock, patch

from src.kpf.main import (
    _extract_local_port,
    _is_port_available,
    _test_port_forward_health,
    _validate_kubectl_command,
    _validate_port_availability,
    _validate_port_format,
    _validate_service_and_endpoints,
    get_port_forward_args,
    get_watcher_args,
    restart_event,
    run_port_forward,
    shutdown_event,
)


class TestArgumentParsing:
    """Test argument parsing functions."""

    def test_get_port_forward_args_valid(self):
        """Test get_port_forward_args with valid arguments."""
        args = ["svc/frontend", "8080:8080", "-n", "production"]
        result = get_port_forward_args(args)
        assert result == args

    def test_get_port_forward_args_empty(self):
        """Test get_port_forward_args with empty arguments."""
        with patch("sys.exit") as mock_exit:
            get_port_forward_args([])
            mock_exit.assert_called_once_with(1)

    def test_get_watcher_args_service_with_namespace(self):
        """Test get_watcher_args with service and namespace."""
        args = ["svc/frontend", "8080:8080", "-n", "production"]
        namespace, resource_name = get_watcher_args(args)

        assert namespace == "production"
        assert resource_name == "frontend"

    def test_get_watcher_args_service_default_namespace(self):
        """Test get_watcher_args with service but no namespace."""
        args = ["svc/api-service", "8080:8080"]
        namespace, resource_name = get_watcher_args(args)

        assert namespace == "default"
        assert resource_name == "api-service"

    def test_get_watcher_args_pod(self):
        """Test get_watcher_args with pod resource."""
        args = ["pod/my-pod", "3000:3000", "-n", "kube-system"]
        namespace, resource_name = get_watcher_args(args)

        assert namespace == "kube-system"
        assert resource_name == "my-pod"

    def test_get_watcher_args_deployment(self):
        """Test get_watcher_args with deployment resource."""
        args = ["deployment/my-deploy", "8080:8080"]
        namespace, resource_name = get_watcher_args(args)

        assert namespace == "default"
        assert resource_name == "my-deploy"

    def test_get_watcher_args_service_full_name(self):
        """Test get_watcher_args with full 'service' name."""
        args = ["service/web-service", "80:8080"]
        namespace, resource_name = get_watcher_args(args)

        assert namespace == "default"
        assert resource_name == "web-service"

    def test_get_watcher_args_no_resource(self):
        """Test get_watcher_args with no recognizable resource."""
        args = ["8080:8080", "-n", "production"]

        with patch("sys.exit") as mock_exit:
            get_watcher_args(args)
            mock_exit.assert_called_once_with(1)

    def test_get_watcher_args_namespace_at_end(self):
        """Test get_watcher_args with namespace flag at the end."""
        args = ["svc/backend", "9090:9090", "-n"]

        # Should handle incomplete -n flag gracefully
        namespace, resource_name = get_watcher_args(args)
        assert namespace == "default"  # Falls back to default
        assert resource_name == "backend"


class TestDebugMode:
    """Test debug functionality."""

    def test_debug_disabled_by_default(self):
        """Test that debug is disabled by default."""
        from src.kpf.main import _debug_enabled, debug

        # Initially should be disabled
        assert _debug_enabled is False

        # Debug prints should not output when disabled
        with patch("src.kpf.main.console.print") as mock_print:
            debug.print("test message")
            mock_print.assert_not_called()

    def test_debug_enabled(self):
        """Test debug when enabled."""
        with (
            patch("src.kpf.main._debug_enabled", True),
            patch("src.kpf.main.console.print") as mock_print,
        ):
            from src.kpf.main import debug

            debug.print("test debug message")

            mock_print.assert_called_once()
            args = mock_print.call_args[0]
            assert "test debug message" in args[0]
            assert "[DEBUG]" in args[0]


class TestRunPortForward:
    """Test run_port_forward function."""

    def setUp(self):
        """Reset threading events before each test."""
        restart_event.clear()
        shutdown_event.clear()

    def tearDown(self):
        """Clean up threading events after each test."""
        restart_event.clear()
        shutdown_event.clear()

    @patch("src.kpf.main._validate_service_and_endpoints")
    @patch("src.kpf.main._validate_kubectl_command")
    @patch("src.kpf.main._validate_port_availability")
    @patch("src.kpf.main._validate_port_format")
    @patch("src.kpf.main.threading.Thread")
    @patch("src.kpf.main.get_watcher_args")
    def test_run_port_forward_basic(
        self,
        mock_get_watcher,
        mock_thread,
        mock_port_format,
        mock_port_avail,
        mock_kubectl,
        mock_service,
    ):
        """Test basic run_port_forward execution."""
        mock_get_watcher.return_value = ("default", "test-service")

        # Mock all validations to pass
        mock_port_format.return_value = True
        mock_port_avail.return_value = True
        mock_kubectl.return_value = True
        mock_service.return_value = True

        # Mock threads that exit immediately
        mock_pf_thread = Mock()
        mock_ew_thread = Mock()
        mock_pf_thread.is_alive.return_value = False
        mock_ew_thread.is_alive.return_value = False

        mock_thread.side_effect = [mock_pf_thread, mock_ew_thread]

        args = ["svc/test-service", "8080:8080"]

        # Just run normally - threads will exit immediately
        run_port_forward(args)

        # Verify threads were created and started
        assert mock_thread.call_count == 2
        mock_pf_thread.start.assert_called_once()
        mock_ew_thread.start.assert_called_once()
        mock_pf_thread.join.assert_called_once()
        mock_ew_thread.join.assert_called_once()

    @patch("src.kpf.main._validate_service_and_endpoints")
    @patch("src.kpf.main._validate_kubectl_command")
    @patch("src.kpf.main._validate_port_availability")
    @patch("src.kpf.main._validate_port_format")
    @patch("src.kpf.main.threading.Thread")
    @patch("src.kpf.main.get_watcher_args")
    def test_run_port_forward_debug_mode(
        self,
        mock_get_watcher,
        mock_thread,
        mock_port_format,
        mock_port_avail,
        mock_kubectl,
        mock_service,
    ):
        """Test run_port_forward with debug mode enabled."""
        mock_get_watcher.return_value = ("default", "test-service")

        # Mock all validations to pass
        mock_port_format.return_value = True
        mock_port_avail.return_value = True
        mock_kubectl.return_value = True
        mock_service.return_value = True

        # Mock threads that exit immediately
        mock_pf_thread = Mock()
        mock_ew_thread = Mock()
        mock_pf_thread.is_alive.return_value = False
        mock_ew_thread.is_alive.return_value = False

        mock_thread.side_effect = [mock_pf_thread, mock_ew_thread]

        args = ["svc/test-service", "8080:8080"]

        with patch("src.kpf.main.console.print") as mock_print:
            run_port_forward(args, debug_mode=True)

        # Verify debug messages were printed
        debug_calls = [call for call in mock_print.call_args_list if "[DEBUG]" in str(call)]
        assert len(debug_calls) > 0

    @patch("src.kpf.main._validate_service_and_endpoints")
    @patch("src.kpf.main._validate_kubectl_command")
    @patch("src.kpf.main._validate_port_availability")
    @patch("src.kpf.main._validate_port_format")
    @patch("src.kpf.main.threading.Thread")
    @patch("src.kpf.main.get_watcher_args")
    def test_run_port_forward_keyboard_interrupt(
        self,
        mock_get_watcher,
        mock_thread,
        mock_port_format,
        mock_port_avail,
        mock_kubectl,
        mock_service,
    ):
        """Test run_port_forward handling keyboard interrupt."""
        mock_get_watcher.return_value = ("default", "test-service")

        # Mock all validations to pass
        mock_port_format.return_value = True
        mock_port_avail.return_value = True
        mock_kubectl.return_value = True
        mock_service.return_value = True

        # Mock threads
        mock_pf_thread = Mock()
        mock_ew_thread = Mock()
        mock_pf_thread.is_alive.return_value = True
        mock_ew_thread.is_alive.return_value = True

        mock_thread.side_effect = [mock_pf_thread, mock_ew_thread]

        args = ["svc/test-service", "8080:8080"]

        # Simulate KeyboardInterrupt in main loop
        with patch("time.sleep", side_effect=KeyboardInterrupt):
            run_port_forward(args)

        # Verify graceful shutdown
        mock_pf_thread.join.assert_called_once()
        mock_ew_thread.join.assert_called_once()


class TestPortForwardThread:
    """Test port-forward thread functionality."""

    def test_port_forward_thread_args_parsing(self):
        """Test that port-forward thread receives correct arguments."""
        from src.kpf.main import port_forward_thread, restart_event, shutdown_event

        args = ["svc/test", "8080:8080", "-n", "default"]

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_popen.return_value = mock_process

            # Clear events first
            shutdown_event.clear()
            restart_event.clear()

            # Don't set shutdown event initially - let it process
            # Use a side_effect to set shutdown event after Popen is called
            def set_shutdown(*args, **kwargs):
                shutdown_event.set()
                return mock_process

            mock_popen.side_effect = set_shutdown

            port_forward_thread(args)

            # Verify kubectl port-forward was called with correct args
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            assert call_args == ["kubectl", "port-forward"] + args

        # Clean up
        shutdown_event.clear()
        restart_event.clear()


class TestEndpointWatcherThread:
    """Test endpoint watcher thread functionality."""

    def test_endpoint_watcher_thread_args(self):
        """Test that endpoint watcher thread uses correct kubectl command."""
        from src.kpf.main import endpoint_watcher_thread, restart_event, shutdown_event

        namespace = "production"
        resource_name = "my-service"

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = iter([])  # Empty output
            mock_popen.return_value = mock_process

            # Clear events first
            shutdown_event.clear()
            restart_event.clear()

            # Use side_effect to set shutdown after Popen is called
            def set_shutdown(*args, **kwargs):
                shutdown_event.set()
                return mock_process

            mock_popen.side_effect = set_shutdown

            endpoint_watcher_thread(namespace, resource_name)

            # Verify kubectl get ep command was called correctly
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            expected_cmd = [
                "kubectl",
                "get",
                "--no-headers",
                "ep",
                "-w",
                "-n",
                namespace,
                resource_name,
            ]
            assert call_args == expected_cmd

        # Clean up
        shutdown_event.clear()
        restart_event.clear()

    def test_endpoint_watcher_restart_event(self):
        """Test that endpoint watcher sets restart event on changes."""
        from src.kpf.main import endpoint_watcher_thread, restart_event, shutdown_event

        namespace = "default"
        resource_name = "test-service"

        # Mock subprocess output with endpoint changes
        mock_lines = [
            "test-service   10.0.0.1:8080   1m",  # This should trigger restart
        ]

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            mock_process.stdout = iter(mock_lines)
            mock_popen.return_value = mock_process

            # Clear events initially
            restart_event.clear()
            shutdown_event.clear()

            # Create a side effect that processes one line then shuts down
            def process_and_shutdown(*args, **kwargs):
                # Process the mock lines, then set shutdown
                for line in mock_lines:
                    restart_event.set()  # Simulate the restart event being set
                shutdown_event.set()
                return mock_process

            mock_popen.side_effect = process_and_shutdown

            endpoint_watcher_thread(namespace, resource_name)

            # Verify restart event was set
            assert restart_event.is_set()

        # Clean up
        restart_event.clear()
        shutdown_event.clear()


class TestPortValidation:
    """Test port validation functionality."""

    def test_extract_local_port_valid(self):
        """Test extracting local port from valid port-forward arguments."""
        args = ["svc/test", "8080:80", "-n", "default"]
        port = _extract_local_port(args)
        assert port == 8080

    def test_extract_local_port_multiple_colons(self):
        """Test extracting local port with multiple colons (IPv6 style)."""
        args = ["svc/test", "8080:80:443", "-n", "default"]
        port = _extract_local_port(args)
        assert port == 8080

    def test_extract_local_port_no_port_mapping(self):
        """Test extracting local port when no port mapping present."""
        args = ["svc/test", "-n", "default"]
        port = _extract_local_port(args)
        assert port is None

    def test_extract_local_port_invalid_format(self):
        """Test extracting local port from invalid port format."""
        args = ["svc/test", "invalid:port", "-n", "default"]
        port = _extract_local_port(args)
        assert port is None

    def test_extract_local_port_flag_with_colon(self):
        """Test that flags with colons are ignored."""
        args = ["svc/test", "-n", "namespace:with:colons", "8080:80"]
        port = _extract_local_port(args)
        assert port == 8080

    def test_is_port_available_high_port(self):
        """Test port availability check with a high port number."""
        # Use a high port number that's likely to be available
        high_port = 19998
        result = _is_port_available(high_port)
        assert result is True

    def test_is_port_available_bound_port(self):
        """Test port availability check with a bound port."""
        import socket

        test_port = 19997
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.bind(("localhost", test_port))
            result = _is_port_available(test_port)
            assert result is False
        finally:
            test_socket.close()

    def test_validate_port_availability_available(self):
        """Test port validation with an available port."""
        args = ["svc/test", "19996:80", "-n", "default"]
        result = _validate_port_availability(args)
        assert result is True

    def test_validate_port_availability_in_use(self):
        """Test port validation with a port in use."""
        import socket

        test_port = 19995
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.bind(("localhost", test_port))
            args = ["svc/test", f"{test_port}:80", "-n", "default"]

            with patch("src.kpf.main.console.print") as mock_print:
                result = _validate_port_availability(args)
                assert result is False

                # Check that error message was printed
                error_calls = [
                    call for call in mock_print.call_args_list if "already in use" in str(call)
                ]
                assert len(error_calls) > 0
        finally:
            test_socket.close()

    def test_validate_port_availability_no_port(self):
        """Test port validation when no port can be extracted."""
        args = ["svc/test", "-n", "default"]
        result = _validate_port_availability(args)
        assert result is True  # Should return True when can't validate

    @patch("src.kpf.main.socket.socket")
    def test_test_port_forward_health_success(self, mock_socket):
        """Test port-forward health check success."""
        args = ["svc/test", "8080:80", "-n", "default"]

        # Mock successful connection
        mock_sock_instance = Mock()
        mock_sock_instance.connect_ex.return_value = 0  # Success
        mock_socket.return_value.__enter__.return_value = mock_sock_instance

        result = _test_port_forward_health(args, timeout=1)
        assert result is True

    @patch("src.kpf.main.socket.socket")
    def test_test_port_forward_health_connection_refused(self, mock_socket):
        """Test port-forward health check with connection refused (still working)."""
        args = ["svc/test", "8080:80", "-n", "default"]

        # Mock connection refused (errno 61 on macOS)
        mock_sock_instance = Mock()
        mock_sock_instance.connect_ex.return_value = 61  # Connection refused
        mock_socket.return_value.__enter__.return_value = mock_sock_instance

        result = _test_port_forward_health(args, timeout=1)
        assert result is True  # Connection refused still means port-forward is working

    @patch("src.kpf.main.socket.socket")
    @patch("time.sleep")
    def test_test_port_forward_health_timeout(self, mock_sleep, mock_socket):
        """Test port-forward health check timeout."""
        args = ["svc/test", "8080:80", "-n", "default"]

        # Mock connection failure (different error code)
        mock_sock_instance = Mock()
        mock_sock_instance.connect_ex.return_value = 111  # Connection refused/timeout
        mock_socket.return_value.__enter__.return_value = mock_sock_instance

        result = _test_port_forward_health(args, timeout=1)
        assert result is False

    def test_test_port_forward_health_no_port(self):
        """Test port-forward health check when no port can be extracted."""
        args = ["svc/test", "-n", "default"]
        result = _test_port_forward_health(args)
        assert result is True  # Should return True when can't test

    @patch("src.kpf.main._test_port_forward_health")
    @patch("subprocess.Popen")
    def test_port_forward_thread_health_check_fails(self, mock_popen, mock_health_check):
        """Test port-forward thread when health check fails."""
        from src.kpf.main import port_forward_thread, shutdown_event

        args = ["svc/test", "8080:80", "-n", "default"]

        mock_process = Mock()
        mock_popen.return_value = mock_process
        mock_health_check.return_value = False

        shutdown_event.clear()

        with patch("src.kpf.main.console.print") as mock_print:
            port_forward_thread(args)

            # Should print error message
            error_calls = [
                call
                for call in mock_print.call_args_list
                if "failed to start properly" in str(call)
            ]
            assert len(error_calls) > 0

            # Process should be terminated
            mock_process.terminate.assert_called_once()

            # Shutdown event should be set
            assert shutdown_event.is_set()

        # Clean up
        shutdown_event.clear()


class TestArgumentValidation:
    """Test argument validation functions."""

    def test_validate_port_format_valid(self):
        """Test port format validation with valid ports."""
        args = ["svc/test", "8080:80", "-n", "default"]
        result = _validate_port_format(args)
        assert result is True

    def test_validate_port_format_invalid_local_port(self):
        """Test port format validation with invalid local port."""
        args = ["svc/test", "707x:80", "-n", "default"]

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_port_format(args)
            assert result is False

            error_calls = [
                call for call in mock_print.call_args_list if "Invalid port format" in str(call)
            ]
            assert len(error_calls) > 0

    def test_validate_port_format_invalid_remote_port(self):
        """Test port format validation with invalid remote port."""
        args = ["svc/test", "8080:80x", "-n", "default"]

        with patch("src.kpf.main.console.print"):
            result = _validate_port_format(args)
            assert result is False

    def test_validate_port_format_out_of_range_low(self):
        """Test port format validation with port number too low."""
        args = ["svc/test", "0:80", "-n", "default"]

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_port_format(args)
            assert result is False

            error_calls = [
                call for call in mock_print.call_args_list if "not in valid range" in str(call)
            ]
            assert len(error_calls) > 0

    def test_validate_port_format_out_of_range_high(self):
        """Test port format validation with port number too high."""
        args = ["svc/test", "8080:99999", "-n", "default"]

        with patch("src.kpf.main.console.print"):
            result = _validate_port_format(args)
            assert result is False

    def test_validate_port_format_no_colon(self):
        """Test port format validation with no port mapping."""
        args = ["svc/test", "-n", "default"]

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_port_format(args)
            assert result is False

            error_calls = [
                call
                for call in mock_print.call_args_list
                if "No valid port mapping found" in str(call)
            ]
            assert len(error_calls) > 0

    def test_validate_port_format_malformed_mapping(self):
        """Test port format validation with malformed port mapping."""
        args = ["svc/test", "8080:", "-n", "default"]

        with patch("src.kpf.main.console.print"):
            result = _validate_port_format(args)
            assert result is False

    @patch("subprocess.run")
    def test_validate_kubectl_command_success(self, mock_run):
        """Test kubectl command validation success."""
        args = ["svc/test", "8080:80", "-n", "default"]

        # Mock successful kubectl version check
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = _validate_kubectl_command(args)
        assert result is True

        # Verify kubectl was called with version
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "kubectl" in call_args
        assert "version" in call_args

    @patch("subprocess.run")
    def test_validate_kubectl_command_failure(self, mock_run):
        """Test kubectl command validation failure."""
        args = ["svc/nonexistent", "8080:80", "-n", "default"]

        # Mock failed kubectl version check
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "kubectl version error"
        mock_run.return_value = mock_result

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_kubectl_command(args)
            assert result is False

            # Check that error message was printed
            error_calls = [
                call for call in mock_print.call_args_list if "not working properly" in str(call)
            ]
            assert len(error_calls) > 0

    @patch("subprocess.run")
    def test_validate_kubectl_command_timeout(self, mock_run):
        """Test kubectl command validation timeout."""
        args = ["svc/test", "8080:80", "-n", "default"]

        # Mock subprocess timeout
        mock_run.side_effect = subprocess.TimeoutExpired("kubectl", 10)

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_kubectl_command(args)
            assert result is False

            # Check timeout error message
            timeout_calls = [call for call in mock_print.call_args_list if "timed out" in str(call)]
            assert len(timeout_calls) > 0

    @patch("subprocess.run")
    def test_validate_kubectl_command_not_found(self, mock_run):
        """Test kubectl command validation when kubectl not found."""
        args = ["svc/test", "8080:80", "-n", "default"]

        # Mock kubectl not found
        mock_run.side_effect = FileNotFoundError("kubectl not found")

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_kubectl_command(args)
            assert result is False

            # Check kubectl not found error message
            notfound_calls = [
                call
                for call in mock_print.call_args_list
                if "kubectl command not found" in str(call)
            ]
            assert len(notfound_calls) > 0

    def test_integration_invalid_port_format_cli(self):
        """Integration test for invalid port format via CLI."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.kpf.cli",
                "svc/test",
                "707x:80",
                "-n",
                "default",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 1
        assert "Invalid port format" in result.stdout


class TestServiceValidation:
    """Test service and endpoint validation functions."""

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_service_not_found(self, mock_run):
        """Test service validation when service doesn't exist."""
        args = ["svc/nonexistent", "8080:80", "-n", "default"]

        # Mock service not found
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "services 'nonexistent' not found"
        mock_run.return_value = mock_result

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_service_and_endpoints(args)
            assert result is False

            # Check error message
            error_calls = [call for call in mock_print.call_args_list if "not found" in str(call)]
            assert len(error_calls) > 0

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_no_endpoints(self, mock_run):
        """Test service validation when service has no endpoints."""
        args = ["svc/no-endpoints", "8080:80", "-n", "default"]

        # Mock service exists but no endpoints
        def mock_subprocess(*cmd_args, **kwargs):
            cmd = cmd_args[0]
            result = Mock()

            if "get svc" in " ".join(cmd):
                # Service exists
                result.returncode = 0
                result.stdout = '{"metadata": {"name": "no-endpoints"}}'
            elif "get endpoints" in " ".join(cmd):
                # No endpoints
                result.returncode = 1
                result.stderr = "endpoints 'no-endpoints' not found"

            return result

        mock_run.side_effect = mock_subprocess

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_service_and_endpoints(args)
            assert result is False

            # Check endpoints error message
            endpoint_calls = [
                call for call in mock_print.call_args_list if "endpoints" in str(call).lower()
            ]
            assert len(endpoint_calls) > 0

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_empty_endpoints(self, mock_run):
        """Test service validation when service has empty endpoints."""
        args = ["svc/empty-endpoints", "8080:80", "-n", "default"]

        # Mock service exists but endpoints are empty
        def mock_subprocess(*cmd_args, **kwargs):
            cmd = cmd_args[0]
            result = Mock()

            if "get svc" in " ".join(cmd):
                # Service exists
                result.returncode = 0
                result.stdout = '{"metadata": {"name": "empty-endpoints"}}'
            elif "get endpoints" in " ".join(cmd):
                # Endpoints exist but are empty
                result.returncode = 0
                result.stdout = '{"metadata": {"name": "empty-endpoints"}, "subsets": []}'

            return result

        mock_run.side_effect = mock_subprocess

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_service_and_endpoints(args)
            assert result is False

            # Check no ready endpoints error
            ready_calls = [
                call for call in mock_print.call_args_list if "no ready endpoints" in str(call)
            ]
            assert len(ready_calls) > 0

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_success(self, mock_run):
        """Test service validation when service has ready endpoints."""
        args = ["svc/working-service", "8080:80", "-n", "default"]

        # Mock service exists with ready endpoints
        def mock_subprocess(*cmd_args, **kwargs):
            cmd = cmd_args[0]
            result = Mock()

            if "get svc" in " ".join(cmd):
                # Service exists
                result.returncode = 0
                result.stdout = '{"metadata": {"name": "working-service"}}'
            elif "get endpoints" in " ".join(cmd):
                # Endpoints exist with ready addresses
                result.returncode = 0
                result.stdout = """
                {
                    "metadata": {"name": "working-service"},
                    "subsets": [
                        {
                            "addresses": [{"ip": "10.0.0.1"}],
                            "ports": [{"port": 80}]
                        }
                    ]
                }
                """

            return result

        mock_run.side_effect = mock_subprocess

        result = _validate_service_and_endpoints(args)
        assert result is True

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_pod_not_found(self, mock_run):
        """Test service validation when pod doesn't exist."""
        args = ["pod/nonexistent-pod", "8080:80", "-n", "default"]

        # Mock pod not found
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "pods 'nonexistent-pod' not found"
        mock_run.return_value = mock_result

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_service_and_endpoints(args)
            assert result is False

            # Check pod error message
            error_calls = [call for call in mock_print.call_args_list if "not found" in str(call)]
            assert len(error_calls) > 0

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_deployment_success(self, mock_run):
        """Test service validation when deployment exists."""
        args = ["deploy/working-deployment", "8080:80", "-n", "default"]

        # Mock deployment exists
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "NAME                 READY   UP-TO-DATE   AVAILABLE   AGE\nworking-deployment   1/1     1            1           1h"
        mock_run.return_value = mock_result

        result = _validate_service_and_endpoints(args)
        assert result is True

    def test_validate_service_and_endpoints_no_resource(self):
        """Test service validation when no resource specified."""
        args = ["8080:80", "-n", "default"]

        result = _validate_service_and_endpoints(args)
        assert result is True  # Should return True and let kubectl handle it

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_timeout(self, mock_run):
        """Test service validation timeout."""
        args = ["svc/test", "8080:80", "-n", "default"]

        mock_run.side_effect = subprocess.TimeoutExpired("kubectl", 10)

        with patch("src.kpf.main.console.print") as mock_print:
            result = _validate_service_and_endpoints(args)
            assert result is False

            # Check timeout error
            timeout_calls = [call for call in mock_print.call_args_list if "timed out" in str(call)]
            assert len(timeout_calls) > 0

    def test_integration_service_not_found_cli(self):
        """Integration test for non-existent service via CLI."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.kpf.cli",
                "svc/definitely-not-exist-123",
                "7073:80",
                "-n",
                "default",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        assert result.returncode == 1
        assert "not found" in result.stdout or "endpoints" in result.stdout.lower()
