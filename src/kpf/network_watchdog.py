#!/usr/bin/env python3
"""Network watchdog to detect zombie connections after laptop sleep/wake."""

import socket
import threading
import urllib.parse
from typing import Callable, Optional


class NetworkWatchdog(threading.Thread):
    """Watchdog thread that monitors K8s API connectivity.

    Detects zombie connections that can occur after laptop sleep/wake
    by actively checking K8s API server reachability.
    """

    def __init__(
        self,
        shutdown_event: threading.Event,
        restart_event: threading.Event,
        interval: int = 5,
        failure_threshold: int = 2,
        debug_callback: Optional[Callable[[str], None]] = None,
    ):
        """Initialize the network watchdog.

        Args:
            shutdown_event: Event to signal shutdown
            restart_event: Event to signal restart needed
            interval: Seconds between connectivity checks
            failure_threshold: Consecutive failures before triggering restart
            debug_callback: Optional callback for debug output
        """
        super().__init__(daemon=True)
        self.shutdown_event = shutdown_event
        self.restart_event = restart_event
        self.interval = interval
        self.failure_threshold = failure_threshold
        self.debug_callback = debug_callback
        self.consecutive_failures = 0
        self._api_server_host: Optional[str] = None
        self._api_server_port: int = 443

    def _debug(self, message: str, rate_limit: bool = False):
        """Print debug message if callback is set."""
        if self.debug_callback:
            self.debug_callback(message, rate_limit)

    def _get_api_server_address(self) -> tuple[Optional[str], int]:
        """Get the K8s API server host and port from kubectl config.

        Returns:
            Tuple of (host, port) or (None, 443) if unable to determine
        """
        if self._api_server_host is not None:
            return self._api_server_host, self._api_server_port

        try:
            import subprocess

            result = subprocess.run(
                [
                    "kubectl",
                    "config",
                    "view",
                    "--minify",
                    "-o",
                    "jsonpath={.clusters[0].cluster.server}",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            server_url = result.stdout.strip()
            if server_url:
                parsed = urllib.parse.urlparse(server_url)
                self._api_server_host = parsed.hostname
                self._api_server_port = parsed.port or 443
                self._debug(f"Network watchdog: API server is {self._api_server_host}:{self._api_server_port}")
                return self._api_server_host, self._api_server_port
        except Exception as e:
            self._debug(f"Network watchdog: Failed to get API server address: {e}")

        return None, 443

    def check_connectivity(self) -> bool:
        """Check connectivity to K8s API server via TCP connection.

        Returns:
            True if reachable, False otherwise
        """
        host, port = self._get_api_server_address()
        if host is None:
            self._debug("Network watchdog: No API server address available", rate_limit=True)
            return True  # Assume OK if we can't determine the address

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                self._debug(f"Network watchdog: API server reachable ({host}:{port})", rate_limit=True)
                return True
            else:
                self._debug(f"Network watchdog: API server unreachable ({host}:{port}), error code: {result}")
                return False
        except socket.timeout:
            self._debug(f"Network watchdog: Connection timeout to {host}:{port}")
            return False
        except socket.gaierror as e:
            self._debug(f"Network watchdog: DNS resolution failed for {host}: {e}")
            return False
        except Exception as e:
            self._debug(f"Network watchdog: Connection error to {host}:{port}: {e}")
            return False

    def run(self):
        """Main watchdog loop - runs in separate thread."""
        self._debug("Network watchdog thread started")

        # Initial delay to let the port-forward establish
        self.shutdown_event.wait(2)

        while not self.shutdown_event.is_set():
            if not self.check_connectivity():
                self.consecutive_failures += 1
                self._debug(
                    f"Network watchdog: Connectivity failure {self.consecutive_failures}/{self.failure_threshold}"
                )

                if self.consecutive_failures >= self.failure_threshold:
                    self._debug("Network watchdog: Threshold reached, triggering restart")
                    self.restart_event.set()
                    self.consecutive_failures = 0
            else:
                if self.consecutive_failures > 0:
                    self._debug("Network watchdog: Connectivity restored")
                self.consecutive_failures = 0

            # Wait for the interval or until shutdown
            self.shutdown_event.wait(self.interval)

        self._debug("Network watchdog thread exiting")
