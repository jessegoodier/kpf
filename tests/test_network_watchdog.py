#!/usr/bin/env python3
"""Tests for the network watchdog module."""

import socket
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from kpf.network_watchdog import NetworkWatchdog


class TestNetworkWatchdog:
    """Tests for NetworkWatchdog class."""

    def test_init_default_values(self):
        """Test NetworkWatchdog initializes with correct default values."""
        shutdown_event = threading.Event()
        restart_event = threading.Event()

        watchdog = NetworkWatchdog(shutdown_event, restart_event)

        assert watchdog.interval == 5
        assert watchdog.failure_threshold == 2
        assert watchdog.consecutive_failures == 0
        assert watchdog.shutdown_event is shutdown_event
        assert watchdog.restart_event is restart_event

    def test_init_custom_values(self):
        """Test NetworkWatchdog initializes with custom values."""
        shutdown_event = threading.Event()
        restart_event = threading.Event()

        watchdog = NetworkWatchdog(
            shutdown_event,
            restart_event,
            interval=10,
            failure_threshold=3,
        )

        assert watchdog.interval == 10
        assert watchdog.failure_threshold == 3

    @patch("subprocess.run")
    def test_get_api_server_address_success(self, mock_run):
        """Test getting API server address from kubectl config."""
        mock_run.return_value = MagicMock(
            stdout="https://192.168.1.100:6443",
            returncode=0,
        )

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)

        host, port = watchdog._get_api_server_address()

        assert host == "192.168.1.100"
        assert port == 6443

    @patch("subprocess.run")
    def test_get_api_server_address_default_port(self, mock_run):
        """Test API server address defaults to port 443 when not specified."""
        mock_run.return_value = MagicMock(
            stdout="https://kubernetes.local",
            returncode=0,
        )

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)

        host, port = watchdog._get_api_server_address()

        assert host == "kubernetes.local"
        assert port == 443

    @patch("subprocess.run")
    def test_get_api_server_address_failure(self, mock_run):
        """Test handling of kubectl config failure."""
        mock_run.side_effect = Exception("kubectl not found")

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)

        host, port = watchdog._get_api_server_address()

        assert host is None
        assert port == 443

    @patch("socket.socket")
    def test_check_connectivity_success(self, mock_socket_class):
        """Test successful connectivity check."""
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 0
        mock_socket_class.return_value = mock_socket

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)
        watchdog._api_server_host = "192.168.1.100"
        watchdog._api_server_port = 6443

        result = watchdog.check_connectivity()

        assert result is True
        mock_socket.connect_ex.assert_called_once_with(("192.168.1.100", 6443))
        mock_socket.close.assert_called_once()

    @patch("socket.socket")
    def test_check_connectivity_failure(self, mock_socket_class):
        """Test failed connectivity check."""
        mock_socket = MagicMock()
        mock_socket.connect_ex.return_value = 111  # Connection refused
        mock_socket_class.return_value = mock_socket

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)
        watchdog._api_server_host = "192.168.1.100"
        watchdog._api_server_port = 6443

        result = watchdog.check_connectivity()

        assert result is False

    @patch("socket.socket")
    def test_check_connectivity_timeout(self, mock_socket_class):
        """Test connectivity check timeout."""
        mock_socket = MagicMock()
        mock_socket.connect_ex.side_effect = socket.timeout("Connection timed out")
        mock_socket_class.return_value = mock_socket

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)
        watchdog._api_server_host = "192.168.1.100"
        watchdog._api_server_port = 6443

        result = watchdog.check_connectivity()

        assert result is False

    @patch("socket.socket")
    def test_check_connectivity_dns_failure(self, mock_socket_class):
        """Test connectivity check DNS resolution failure."""
        mock_socket = MagicMock()
        mock_socket.connect_ex.side_effect = socket.gaierror("Name resolution failed")
        mock_socket_class.return_value = mock_socket

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)
        watchdog._api_server_host = "nonexistent.local"
        watchdog._api_server_port = 6443

        result = watchdog.check_connectivity()

        assert result is False

    def test_check_connectivity_no_host(self):
        """Test connectivity check returns True when no host is available."""
        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)
        watchdog._api_server_host = None

        result = watchdog.check_connectivity()

        assert result is True  # Assume OK if we can't determine the address

    @patch.object(NetworkWatchdog, "check_connectivity")
    def test_failure_threshold_triggers_restart(self, mock_check):
        """Test that reaching failure threshold triggers restart event."""
        mock_check.return_value = False

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(
            shutdown_event,
            restart_event,
            interval=0.05,
            failure_threshold=2,
        )

        # Start the watchdog
        watchdog.start()

        # Wait for initial delay (2s) plus enough time for 2 failures
        # Use a loop to check periodically instead of fixed sleep
        for _ in range(60):  # Check up to 3 seconds
            if restart_event.is_set():
                break
            time.sleep(0.05)

        # Signal shutdown
        shutdown_event.set()
        watchdog.join(timeout=1)

        # Verify restart was triggered
        assert restart_event.is_set()

    @patch.object(NetworkWatchdog, "check_connectivity")
    def test_recovery_resets_failure_count(self, mock_check):
        """Test that successful check resets failure count."""
        # First call fails, second succeeds
        mock_check.side_effect = [False, True, True, True, True]

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(
            shutdown_event,
            restart_event,
            interval=0.05,
            failure_threshold=3,
        )

        watchdog.start()
        time.sleep(0.3)
        shutdown_event.set()
        watchdog.join(timeout=1)

        # Restart should not have been triggered (only 1 failure before recovery)
        assert not restart_event.is_set()

    @patch.object(NetworkWatchdog, "check_connectivity")
    def test_shutdown_stops_thread(self, mock_check):
        """Test that setting shutdown_event stops the watchdog thread."""
        mock_check.return_value = True

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(
            shutdown_event,
            restart_event,
            interval=0.1,
        )

        watchdog.start()
        assert watchdog.is_alive()

        # Signal shutdown
        shutdown_event.set()
        watchdog.join(timeout=2)

        assert not watchdog.is_alive()

    def test_debug_callback(self):
        """Test that debug callback is called."""
        debug_messages = []

        def capture_debug(msg, rate_limit=False):
            debug_messages.append(msg)

        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(
            shutdown_event,
            restart_event,
            debug_callback=capture_debug,
        )

        watchdog._debug("test message")

        assert len(debug_messages) == 1
        assert "test message" in debug_messages[0]

    def test_is_daemon_thread(self):
        """Test that watchdog is a daemon thread."""
        shutdown_event = threading.Event()
        restart_event = threading.Event()
        watchdog = NetworkWatchdog(shutdown_event, restart_event)

        assert watchdog.daemon is True
