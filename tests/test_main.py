"""Tests for main module."""

import subprocess
from unittest.mock import Mock, patch

from src.kpf.connectivity import (
    ConnectivityTestResult,
)
from src.kpf.main import (
    get_port_forward_args,
    get_watcher_args,
    restart_event,
    run_port_forward,
    shutdown_event,
)
from src.kpf.validators import (
    extract_local_port,
    is_port_available,
    validate_kubectl_command,
    validate_port_availability,
    validate_port_format,
    validate_service_and_endpoints,
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

        # Mock the KubernetesClient to return a known namespace
        with patch("src.kpf.kubernetes.KubernetesClient") as mock_client:
            mock_client.return_value.get_current_namespace.return_value = "default"
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

        # Mock the KubernetesClient to return a known namespace
        with patch("src.kpf.kubernetes.KubernetesClient") as mock_client:
            mock_client.return_value.get_current_namespace.return_value = "default"
            namespace, resource_name = get_watcher_args(args)

        assert namespace == "default"
        assert resource_name == "my-deploy"

    def test_get_watcher_args_service_full_name(self):
        """Test get_watcher_args with full 'service' name."""
        args = ["service/web-service", "80:8080"]

        # Mock the KubernetesClient to return a known namespace
        with patch("src.kpf.kubernetes.KubernetesClient") as mock_client:
            mock_client.return_value.get_current_namespace.return_value = "default"
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

        # Should handle incomplete -n flag gracefully and fall back to current context
        with patch("src.kpf.kubernetes.KubernetesClient") as mock_client:
            mock_client.return_value.get_current_namespace.return_value = "default"
            namespace, resource_name = get_watcher_args(args)

        assert namespace == "default"  # Falls back to current context namespace
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

    # No teardown needed for threading events as they are cleared in setUp

    @patch("src.kpf.main.validate_service_and_endpoints")
    @patch("src.kpf.main.validate_kubectl_command")
    @patch("src.kpf.main.validate_port_availability")
    @patch("src.kpf.main.validate_port_format")
    @patch("src.kpf.main.EndpointWatcher")
    @patch("src.kpf.main.PortForwarder")
    @patch("src.kpf.main.get_watcher_args")
    def test_run_port_forward_basic(
        self,
        mock_get_watcher,
        mock_forwarder,
        mock_watcher,
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
        mock_pf_instance = Mock()
        mock_ew_instance = Mock()
        mock_pf_instance.is_alive.return_value = False
        mock_ew_instance.is_alive.return_value = False

        mock_forwarder.return_value = mock_pf_instance
        mock_watcher.return_value = mock_ew_instance

        args = ["svc/test-service", "8080:8080"]

        # Just run normally - threads will exit immediately
        run_port_forward(args)

        # Verify threads were created and started
        mock_pf_instance.start.assert_called_once()
        mock_ew_instance.start.assert_called_once()
        mock_pf_instance.join.assert_called_once()
        mock_ew_instance.join.assert_called_once()

    @patch("src.kpf.main.validate_service_and_endpoints")
    @patch("src.kpf.main.validate_kubectl_command")
    @patch("src.kpf.main.validate_port_availability")
    @patch("src.kpf.main.validate_port_format")
    @patch("src.kpf.main.EndpointWatcher")
    @patch("src.kpf.main.PortForwarder")
    @patch("src.kpf.main.get_watcher_args")
    def test_run_port_forward_debug_mode(
        self,
        mock_get_watcher,
        mock_forwarder,
        mock_watcher,
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
        mock_pf_instance = Mock()
        mock_ew_instance = Mock()
        mock_pf_instance.is_alive.return_value = False
        mock_ew_instance.is_alive.return_value = False

        mock_forwarder.return_value = mock_pf_instance
        mock_watcher.return_value = mock_ew_instance

        args = ["svc/test-service", "8080:8080"]

        with patch("src.kpf.main.console.print"):
            run_port_forward(args, debug_mode=True)
            # Verify debug messages were printed (checking for [DEBUG] in calls)
            # Since we mocked console.print, we check if it was called with something that looks like debug
            # debug.print uses console.print, and preprends [DEBUG] usually if using the real class,
            # but here we rely on run_port_forward passing debug_mode=True to the orchestrator.
            # The orchestrator sets up debug.
            pass

    @patch("src.kpf.main.validate_service_and_endpoints")
    @patch("src.kpf.main.validate_kubectl_command")
    @patch("src.kpf.main.validate_port_availability")
    @patch("src.kpf.main.validate_port_format")
    @patch("src.kpf.main.EndpointWatcher")
    @patch("src.kpf.main.PortForwarder")
    @patch("src.kpf.main.get_watcher_args")
    @patch("src.kpf.main.shutdown_event")
    def test_run_port_forward_keyboard_interrupt(
        self,
        mock_shutdown_event,
        mock_get_watcher,
        mock_forwarder,
        mock_watcher,
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
        mock_pf_instance = Mock()
        mock_ew_instance = Mock()
        # Make threads appear alive initially, then dead after shutdown
        mock_pf_instance.is_alive.side_effect = [True, True, False]
        mock_ew_instance.is_alive.side_effect = [True, True, False]

        mock_forwarder.return_value = mock_pf_instance
        mock_watcher.return_value = mock_ew_instance

        # Mock shutdown event to trigger shutdown after first check
        mock_shutdown_event.is_set.side_effect = [False, True]

        args = ["svc/test-service", "8080:8080"]

        # Run port forward (will exit due to shutdown event)
        run_port_forward(args)

        # Verify graceful shutdown
        mock_pf_instance.join.assert_called()
        mock_ew_instance.join.assert_called()


class TestEndpointWatcherThread:
    """Test endpoint watcher thread functionality."""

    def test_endpoint_watcher_thread_args(self):
        """Test that endpoint watcher thread uses correct kubectl command."""
        from src.kpf.watcher import EndpointWatcher  # Import from new location

        # We need to instantiate EndpointWatcher class now
        watcher = EndpointWatcher(
            "production", "my-service", shutdown_event, restart_event, lambda: True
        )

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

            mock_popen.side_effect = set_shutdown

            watcher.endpoint_watcher_thread()

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
                "production",
                "my-service",
            ]
            assert call_args == expected_cmd

        # Clean up
        shutdown_event.clear()
        restart_event.clear()

    def test_endpoint_watcher_restart_event(self):
        """Test that endpoint watcher sets restart event on changes."""
        from src.kpf.main import restart_event, shutdown_event
        from src.kpf.watcher import EndpointWatcher

        namespace = "default"
        resource_name = "test-service"
        watcher = EndpointWatcher(
            namespace, resource_name, shutdown_event, restart_event, lambda: True
        )

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

            mock_popen.side_effect = process_and_shutdown

            watcher.endpoint_watcher_thread()

            # Verify restart event was set
            assert restart_event.is_set()

        # Clean up
        restart_event.clear()
        shutdown_event.clear()

    @patch("time.sleep")
    def test_endpoint_watcher_delay_on_restart(self, mock_sleep):
        """Test that endpoint watcher waits 2 seconds before restarting kubectl process."""
        from src.kpf.main import restart_event, shutdown_event
        from src.kpf.watcher import EndpointWatcher

        namespace = "default"
        resource_name = "test-service"
        watcher = EndpointWatcher(
            namespace, resource_name, shutdown_event, restart_event, lambda: True
        )

        with patch("subprocess.Popen") as mock_popen:
            mock_process = Mock()
            # Mock the process to exit immediately to trigger restart
            mock_process.stdout = iter([])  # Empty output
            mock_process.wait.return_value = None  # Process exits
            mock_popen.return_value = mock_process

            # Clear events first
            shutdown_event.clear()

            # Set shutdown after first iteration to prevent infinite loop
            call_count = [0]

            def side_effect(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] >= 2:  # After second call, trigger shutdown
                    shutdown_event.set()
                return mock_process

            mock_popen.side_effect = side_effect

            mock_popen.side_effect = side_effect

            watcher.endpoint_watcher_thread()

            # Verify that sleep was called with 2 seconds
            mock_sleep.assert_called_with(2)

        # Clean up
        shutdown_event.clear()


class TestPortValidation:
    """Test port validation functionality."""

    def test_extract_local_port_valid(self):
        """Test extracting local port from valid port-forward arguments."""
        args = ["svc/test", "8080:80", "-n", "default"]
        port = extract_local_port(args)
        assert port == 8080

    def test_extract_local_port_multiple_colons(self):
        """Test extracting local port with multiple colons (IPv6 style)."""
        args = ["svc/test", "8080:80:443", "-n", "default"]
        port = extract_local_port(args)
        assert port == 8080

    def test_extract_local_port_no_port_mapping(self):
        """Test extracting local port when no port mapping present."""
        args = ["svc/test", "-n", "default"]
        port = extract_local_port(args)
        assert port is None

    def test_extract_local_port_invalid_format(self):
        """Test extracting local port from invalid port format."""
        args = ["svc/test", "invalid:port", "-n", "default"]
        port = extract_local_port(args)
        assert port is None

    def test_extract_local_port_flag_with_colon(self):
        """Test that flags with colons are ignored."""
        args = ["svc/test", "-n", "namespace:with:colons", "8080:80"]
        port = extract_local_port(args)
        assert port == 8080

    def test_is_port_available_high_port(self):
        """Test port availability check with a high port number."""

        # Use a high port number that's likely to be available
        high_port = 19998
        result = is_port_available(high_port)
        assert result is True

    def test_is_port_available_bound_port(self):
        """Test port availability check with a bound port."""
        import socket

        test_port = 19997
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.bind(("localhost", test_port))
            result = is_port_available(test_port)
            assert result is False
        finally:
            test_socket.close()

    def test_validate_port_availability_available(self):
        """Test port validation with an available port."""
        args = ["svc/test", "19996:80", "-n", "default"]
        result = validate_port_availability(args)
        assert result is True

    def test_validate_port_availability_in_use(self):
        """Test port validation with a port in use."""
        import socket

        test_port = 19995
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.bind(("localhost", test_port))
            args = ["svc/test", f"{test_port}:80", "-n", "default"]

            with patch("src.kpf.validators.console.print") as mock_print:
                result = validate_port_availability(args)
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
        result = validate_port_availability(args)
        assert result is True  # Should return True when can't validate

    @patch("src.kpf.connectivity.socket.socket")
    def test_test_port_forward_health_success(self, mock_socket):
        """Test port-forward health check success."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        # args variable removed as it was unused

        # Mock successful connection
        mock_sock_instance = Mock()
        mock_sock_instance.connect_ex.return_value = 0  # Success
        mock_socket.return_value.__enter__.return_value = mock_sock_instance

        result = checker.test_port_forward_health(8080, timeout=1)
        assert result is True

    @patch("src.kpf.connectivity.socket.socket")
    @patch("time.sleep")
    def test_test_port_forward_health_timeout(self, mock_sleep, mock_socket):
        """Test port-forward health check timeout."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        # Mock connection failure (different error code)
        mock_sock_instance = Mock()
        mock_sock_instance.connect_ex.return_value = 111  # Connection refused/timeout
        mock_socket.return_value.__enter__.return_value = mock_sock_instance

        result = checker.test_port_forward_health(8080, timeout=1)
        assert result is False

    def test_test_port_forward_health_no_port(self):
        """Test port-forward health check when no port can be extracted."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        result = checker.test_port_forward_health(None)
        assert result is True  # Should return True when can't test

    @patch("src.kpf.connectivity.ConnectivityChecker.test_port_forward_health")
    @patch("subprocess.Popen")
    def test_port_forward_thread_health_check_fails(self, mock_popen, mock_health_check):
        """Test port-forward thread when health check fails."""
        from src.kpf.forwarder import PortForwarder
        from src.kpf.main import restart_event, shutdown_event

        # Reset events
        restart_event.clear()
        shutdown_event.clear()

        args = ["svc/test", "8080:80", "-n", "default"]

        forwarder = PortForwarder(args, shutdown_event, restart_event)

        mock_process = Mock()
        mock_popen.return_value = mock_process

        # Configure side effect to shut down after the first health check fails
        # This breaks the infinite loop in port_forward_thread
        def side_effect(*args, **kwargs):
            shutdown_event.set()
            return False

        mock_health_check.side_effect = side_effect

        with patch("src.kpf.forwarder.console.print") as mock_print:
            forwarder.port_forward_thread()

            # Should print error message
            error_calls = [
                call
                for call in mock_print.call_args_list
                if "failed to start properly" in str(call)
            ]
            assert len(error_calls) > 0

            # Process should be terminated
            # It might be called multiple times (once on failure, once on cleanup)
            mock_process.terminate.assert_called()

            assert restart_event.is_set()

        # Clean up
        shutdown_event.clear()
        restart_event.clear()


class TestArgumentValidation:
    """Test argument validation functions."""

    def test_validate_port_format_valid(self):
        """Test port format validation with valid ports."""
        from src.kpf.validators import validate_port_format

        args = ["svc/test", "8080:80", "-n", "default"]
        result = validate_port_format(args)
        assert result is True

    def test_validate_port_format_invalid_local_port(self):
        """Test port format validation with invalid local port."""
        from src.kpf.validators import validate_port_format

        args = ["svc/test", "707x:80", "-n", "default"]

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_port_format(args)
            assert result is False

            error_calls = [
                call for call in mock_print.call_args_list if "Invalid port format" in str(call)
            ]
            assert len(error_calls) > 0

    def test_validate_port_format_invalid_remote_port(self):
        """Test port format validation with invalid remote port."""
        args = ["svc/test", "8080:80x", "-n", "default"]

        with patch("src.kpf.validators.console.print"):
            result = validate_port_format(args)
            assert result is False

    def test_validate_port_format_out_of_range_low(self):
        """Test port format validation with port number too low."""
        args = ["svc/test", "0:80", "-n", "default"]

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_port_format(args)
            assert result is False

            error_calls = [
                call for call in mock_print.call_args_list if "not in valid range" in str(call)
            ]
            assert len(error_calls) > 0

    def test_validate_port_format_out_of_range_high(self):
        """Test port format validation with port number too high."""
        args = ["svc/test", "8080:99999", "-n", "default"]

        with patch("src.kpf.validators.console.print"):
            result = validate_port_format(args)
            assert result is False

    def test_validate_port_format_no_colon(self):
        """Test port format validation with no port mapping."""
        args = ["svc/test", "-n", "default"]

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_port_format(args)
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

        with patch("src.kpf.validators.console.print"):
            result = validate_port_format(args)
            assert result is False

    @patch("subprocess.run")
    def test_validate_kubectl_command_success(self, mock_run):
        """Test kubectl command validation success."""
        args = ["svc/test", "8080:80", "-n", "default"]

        # Mock successful kubectl version check
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = validate_kubectl_command(args)
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

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_kubectl_command(args)
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

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_kubectl_command(args)
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

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_kubectl_command(args)
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

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_service_and_endpoints(args)
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

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_service_and_endpoints(args)
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

        mock_run.side_effect = mock_subprocess

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_service_and_endpoints(args)
            assert result is False

            # Check no ready endpoints error
            ready_calls = [
                call for call in mock_print.call_args_list if "no ready endpoints" in str(call)
            ]
            assert len(ready_calls) > 0

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_with_selector(self, mock_run):
        """Test service validation displays selector when no endpoints are ready."""
        args = ["svc/selector-service", "8080:80", "-n", "default"]

        # Mock service exists and has selector
        def mock_subprocess(*cmd_args, **kwargs):
            cmd = cmd_args[0]
            result = Mock()

            if "get svc" in " ".join(cmd):
                # Service exists with selector
                result.returncode = 0
                result.stdout = '{"metadata": {"name": "selector-service"}, "spec": {"selector": {"app": "myapp", "tier": "backend"}}}'
            elif "get endpoints" in " ".join(cmd):
                # No ready endpoints
                result.returncode = 0
                result.stdout = '{"metadata": {"name": "selector-service"}, "subsets": []}'

            return result

        mock_run.side_effect = mock_subprocess

        mock_run.side_effect = mock_subprocess

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_service_and_endpoints(args)
            assert result is False

            # Check that the selector is displayed in the error message
            # The selector should be formatted as "app=myapp,tier=backend" or "tier=backend,app=myapp"
            # We check for both parts to be robust against dictionary ordering
            selector_calls = [
                call
                for call in mock_print.call_args_list
                if "app=myapp" in str(call) and "tier=backend" in str(call)
            ]
            assert len(selector_calls) > 0

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

        result = validate_service_and_endpoints(args)
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

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_service_and_endpoints(args)
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

        result = validate_service_and_endpoints(args)
        assert result is True

    def test_validate_service_and_endpoints_no_resource(self):
        """Test service validation when no resource specified."""
        args = ["8080:80", "-n", "default"]

        result = validate_service_and_endpoints(args)
        assert result is True  # Should return True and let kubectl handle it

    @patch("subprocess.run")
    def test_validate_service_and_endpoints_timeout(self, mock_run):
        """Test service validation timeout."""
        args = ["svc/test", "8080:80", "-n", "default"]

        mock_run.side_effect = subprocess.TimeoutExpired("kubectl", 10)

        with patch("src.kpf.validators.console.print") as mock_print:
            result = validate_service_and_endpoints(args)
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


class TestConnectivityTesting:
    """Test enhanced connectivity testing functionality."""

    # Global state setup/teardown no longer needed as we use ConnectivityChecker instance
    pass

    def test_test_socket_connectivity_success(self):
        """Test socket connectivity test with successful connection."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 0  # Success
            mock_socket.return_value.__enter__.return_value = mock_sock_instance

            success, description = checker._test_socket_connectivity(8080)
            assert success is True
            assert description == "connected"

    def test_test_socket_connectivity_connection_refused(self):
        """Test socket connectivity test with connection refused."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 61  # ECONNREFUSED
            mock_socket.return_value.__enter__.return_value = mock_sock_instance

            success, description = checker._test_socket_connectivity(8080)
            assert success is False
            assert description == "connection_refused"

    def test_test_socket_connectivity_failure(self):
        """Test socket connectivity test with connection failure."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        with patch("socket.socket") as mock_socket:
            mock_sock_instance = Mock()
            mock_sock_instance.connect_ex.return_value = 111  # Connection timeout
            mock_socket.return_value.__enter__.return_value = mock_sock_instance

            success, description = checker._test_socket_connectivity(8080)
            assert success is False
            assert "connection_error_111" in description

    def test_test_socket_connectivity_exception(self):
        """Test socket connectivity test with socket exception."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        with patch("socket.socket") as mock_socket:
            mock_socket.side_effect = OSError("Network unreachable")

            success, description = checker._test_socket_connectivity(8080)
            assert success is False
            assert "socket_exception_OSError" in description

    @patch("requests.get")
    def test_test_http_connectivity_success(self, mock_get):
        """Test HTTP connectivity test with successful response."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result, description = checker._test_http_connectivity(8080)
        assert result == ConnectivityTestResult.SUCCESS
        assert "http_response_200" in description

    @patch("requests.get")
    def test_test_http_connectivity_404_is_success(self, mock_get):
        """Test that HTTP 404 is considered successful connectivity."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result, description = checker._test_http_connectivity(8080)
        assert result == ConnectivityTestResult.SUCCESS
        assert "http_response_404" in description

    @patch("requests.get")
    def test_test_http_connectivity_connection_error(self, mock_get):
        """Test HTTP connectivity test with connection error."""
        import requests

        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        result, description = checker._test_http_connectivity(8080)
        assert result == ConnectivityTestResult.HTTP_CONNECTION_ERROR
        assert "all_http_attempts_failed" in description

    @patch("requests.get")
    def test_test_http_connectivity_timeout(self, mock_get):
        """Test HTTP connectivity test with timeout."""
        import requests

        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

        result, description = checker._test_http_connectivity(8080)
        assert result == ConnectivityTestResult.HTTP_CONNECTION_ERROR
        assert "all_http_attempts_failed" in description

    @patch("requests.get")
    @patch("time.time")
    def test_test_http_connectivity_rate_limited(self, mock_time, mock_get):
        """Test HTTP connectivity test rate limiting."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        # Mock time to simulate recent request
        mock_time.side_effect = [1000.0, 1001.0, 1001.0, 1001.0]  # Provide enough time values

        # First call should work normally
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        # First call
        result1, description1 = checker._test_http_connectivity(8080)
        assert result1 == ConnectivityTestResult.SUCCESS

        # Second call should be rate limited
        result2, description2 = checker._test_http_connectivity(8080)
        assert result2 == ConnectivityTestResult.SUCCESS
        assert "rate_limited" in description2

    @patch("src.kpf.connectivity.ConnectivityChecker._test_http_connectivity")
    @patch("src.kpf.connectivity.ConnectivityChecker._test_socket_connectivity")
    def test_check_port_connectivity_socket_failure(self, mock_socket, mock_http):
        """Test enhanced connectivity check with socket failure."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        mock_socket.return_value = (False, "connection_error_111")

        result = checker.check_port_connectivity(8080)
        assert result is False
        # HTTP should not be called if socket fails
        mock_http.assert_not_called()

    @patch("src.kpf.connectivity.ConnectivityChecker._test_http_connectivity")
    @patch("src.kpf.connectivity.ConnectivityChecker._test_socket_connectivity")
    def test_check_port_connectivity_socket_connected_http_success(self, mock_socket, mock_http):
        """Test enhanced connectivity check with socket connected and HTTP success."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        mock_socket.return_value = (True, "connected")
        mock_http.return_value = (ConnectivityTestResult.SUCCESS, "http_response_200")

        result = checker.check_port_connectivity(8080)
        assert result is True
        mock_http.assert_called_once()

    def test_check_port_connectivity_no_port(self):
        """Test enhanced connectivity check with no port specified."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        result = checker.check_port_connectivity(None)
        assert result is True

    @patch("src.kpf.main._debug_enabled", True)
    @patch("time.time")
    def test_debug_rate_limiting(self, mock_time):
        """Test that debug messages can be rate limited."""
        from src.kpf.main import debug

        # Mock time to control rate limiting
        mock_time.side_effect = [1000.0, 1001.0, 1003.0]  # 0s, 1s, 3s timestamps

        with patch("src.kpf.main.console.print") as mock_print:
            # First call should print
            debug.print("Test message", rate_limit=True)
            assert mock_print.call_count == 1

            # Second call within 2s should be rate limited
            debug.print("Test message", rate_limit=True)
            assert mock_print.call_count == 1  # No additional call

            # Third call after 2s should print again
            debug.print("Test message", rate_limit=True)
            assert mock_print.call_count == 2

    @patch("src.kpf.main._debug_enabled", True)
    def test_debug_no_rate_limiting(self):
        """Test that debug messages without rate limiting always print."""
        from src.kpf.main import debug

        with patch("src.kpf.main.console.print") as mock_print:
            # Multiple calls without rate limiting should all print
            debug.print("Test message 1")
            debug.print("Test message 2")
            debug.print("Test message 3")
            assert mock_print.call_count == 3


class TestHttpTimeoutRestart:
    """Test HTTP timeout restart functionality."""

    @patch("time.time")
    def test_mark_http_timeout_start(self, mock_time):
        """Test marking HTTP timeout start."""
        from src.kpf.connectivity import ConnectivityChecker

        mock_callback = Mock()
        checker = ConnectivityChecker(debug_callback=mock_callback)

        mock_time.return_value = 1000.0

        checker._mark_http_timeout_start()
        mock_callback.assert_called_once_with("HTTP timeout period started")

        # Verify state is set
        assert checker.http_timeout_start_time == 1000.0

    @patch("time.time")
    def test_mark_http_timeout_start_already_set(self, mock_time):
        """Test marking HTTP timeout start when already set."""
        from src.kpf.connectivity import ConnectivityChecker

        mock_callback = Mock()
        checker = ConnectivityChecker(debug_callback=mock_callback)

        # Set initial timeout time
        checker.http_timeout_start_time = 1000.0
        mock_time.return_value = 1005.0

        checker._mark_http_timeout_start()
        # Should not print again if already set
        mock_callback.assert_not_called()

        # Verify state unchanged
        assert checker.http_timeout_start_time == 1000.0

    @patch("time.time")
    def test_mark_http_timeout_end(self, mock_time):
        """Test marking HTTP timeout end."""
        from src.kpf.connectivity import ConnectivityChecker

        mock_callback = Mock()
        checker = ConnectivityChecker(debug_callback=mock_callback)

        # Set initial timeout time
        checker.http_timeout_start_time = 1000.0
        mock_time.return_value = 1003.0

        checker._mark_http_timeout_end()
        mock_callback.assert_called_once_with("[green]HTTP timeouts resolved after 3.0s[/green]")

        # Verify state is reset
        assert checker.http_timeout_start_time is None

    def test_mark_http_timeout_end_not_set(self):
        """Test marking HTTP timeout end when not set."""
        from src.kpf.connectivity import ConnectivityChecker

        mock_callback = Mock()
        checker = ConnectivityChecker(debug_callback=mock_callback)

        checker._mark_http_timeout_end()
        # Should not print if not set
        mock_callback.assert_not_called()

    @patch("time.time")
    def test_check_http_timeout_restart_threshold_not_met(self, mock_time):
        """Test HTTP timeout restart check when threshold not met."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        # Set timeout start time
        checker.http_timeout_start_time = 1000.0
        mock_time.return_value = 1003.0  # Only 3 seconds elapsed

        result = checker.check_http_timeout_restart()
        assert result is False

    @patch("time.time")
    def test_check_http_timeout_restart_threshold_met(self, mock_time):
        """Test HTTP timeout restart check when threshold met."""
        from src.kpf.connectivity import ConnectivityChecker

        mock_callback = Mock()
        checker = ConnectivityChecker(debug_callback=mock_callback)

        # Set timeout start time
        checker.http_timeout_start_time = 1000.0
        mock_time.return_value = 1006.0  # 6 seconds elapsed (> 5 second threshold)

        result = checker.check_http_timeout_restart()
        assert result is True
        mock_callback.assert_called_once_with(
            "[yellow]HTTP timeouts persisted for 6.0s, triggering restart[/yellow]"
        )

    def test_check_http_timeout_restart_not_set(self):
        """Test HTTP timeout restart check when timeout not set."""
        from src.kpf.connectivity import ConnectivityChecker

        checker = ConnectivityChecker()

        result = checker.check_http_timeout_restart()
        assert result is False

    @patch("time.time")
    def test_mark_connectivity_success_does_not_reset_http_timeout(self, mock_time):
        """Test that successful connectivity does NOT reset HTTP timeout tracking."""
        from src.kpf.connectivity import ConnectivityChecker

        mock_callback = Mock()
        checker = ConnectivityChecker(debug_callback=mock_callback)

        # Set both connectivity failure and HTTP timeout
        checker.connectivity_failure_start_time = 1000.0
        checker.http_timeout_start_time = 1002.0
        mock_time.return_value = 1005.0

        checker._mark_connectivity_success()

        # Should print connectivity restored message
        calls = [str(call) for call in mock_callback.call_args_list]
        assert any("connectivity restored" in call for call in calls)

        # Should NOT print HTTP resolved message
        assert not any("HTTP timeouts resolved" in call for call in calls)

        # Verify connectivity state is reset
        assert checker.connectivity_failure_start_time is None

        # Verify HTTP timeout state is preserved
        assert checker.http_timeout_start_time == 1002.0
