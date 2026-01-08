import socket
import ssl
import time
from enum import Enum
from typing import Tuple

import requests
from requests.exceptions import SSLError
from rich.console import Console

console = Console()


class ConnectivityTestResult(Enum):
    """Result of connectivity testing."""

    SUCCESS = "success"
    SOCKET_FAILURE = "socket_failure"
    HTTP_CONNECTION_ERROR = "http_connection_error"
    HTTP_TIMEOUT = "http_timeout"
    UNKNOWN_ERROR = "unknown_error"


class ConnectivityChecker:
    def __init__(self, debug_callback=None, run_http_health_checks: bool = False):
        self.debug_print = debug_callback if debug_callback else lambda msg, rate_limit=False: None
        self.run_http_health_checks = run_http_health_checks

        # Track connectivity failure state
        self.connectivity_failure_start_time = None
        self.CONNECTIVITY_CHECK_INTERVAL = 2.0  # Check every 2 seconds minimum
        self.CONNECTIVITY_FAILURE_TIMEOUT = 10.0  # Exit after 10 seconds of failures
        self.HTTP_TIMEOUT = 3.0  # HTTP request timeout
        self.HTTP_RETRY_INTERVAL = 2.0  # Minimum interval between HTTP retries

        # Connection health tracking
        self.last_http_attempt_time = 0

        # HTTP timeout specific tracking
        self.http_timeout_start_time = None
        self.HTTP_TIMEOUT_RESTART_THRESHOLD = 5.0  # Restart if HTTP timeouts persist for 5 seconds

    def _mark_connectivity_failure(self, reason: str):
        """Mark the start of a connectivity failure period."""
        if self.connectivity_failure_start_time is None:
            self.connectivity_failure_start_time = time.time()
            self.debug_print(f"Port connectivity failure started: {reason}")

    def _mark_connectivity_success(self):
        """Mark successful connectivity, resetting failure tracking."""
        if self.connectivity_failure_start_time is not None:
            failure_duration = time.time() - self.connectivity_failure_start_time
            self.debug_print(
                f"[green]Port connectivity restored after {failure_duration:.1f}s[/green]"
            )
            self.connectivity_failure_start_time = None

    def check_connectivity_failure_timeout(self):
        """Check if connectivity has been failing for too long and should trigger program exit."""
        if self.connectivity_failure_start_time is None:
            return False  # No failure in progress

        failure_duration = time.time() - self.connectivity_failure_start_time
        return failure_duration >= self.CONNECTIVITY_FAILURE_TIMEOUT

    def get_connectivity_failure_duration(self):
        """Get the duration of the current connectivity failure."""
        if self.connectivity_failure_start_time is None:
            return 0
        return time.time() - self.connectivity_failure_start_time

    def _mark_http_timeout_start(self):
        """Mark the start of an HTTP timeout period."""
        if self.http_timeout_start_time is None:
            self.http_timeout_start_time = time.time()
            self.debug_print("HTTP timeout period started")

    def _mark_http_timeout_end(self):
        """Mark the end of HTTP timeout issues."""
        if self.http_timeout_start_time is not None:
            timeout_duration = time.time() - self.http_timeout_start_time
            self.debug_print(f"[green]HTTP timeouts resolved after {timeout_duration:.1f}s[/green]")
            self.http_timeout_start_time = None

    def check_http_timeout_restart(self):
        """Check if HTTP timeouts have been persistent and should trigger restart."""
        if self.http_timeout_start_time is None:
            return False  # No timeout in progress

        timeout_duration = time.time() - self.http_timeout_start_time
        if timeout_duration >= self.HTTP_TIMEOUT_RESTART_THRESHOLD:
            self.debug_print(
                f"[yellow]HTTP timeouts persisted for {timeout_duration:.1f}s, triggering restart[/yellow]"
            )
            return True
        return False

    def test_port_forward_health(self, local_port: int, timeout: int = 10):
        """Test if port-forward is working by checking if the local port becomes active."""
        if not self.run_http_health_checks:
            self.debug_print("Health checks disabled, skipping port-forward health test")
            return True  # Assume it's working when health checks are disabled

        if local_port is None:
            self.debug_print("Could not extract local port for health check")
            return True  # Can't test, assume it's working

        self.debug_print(f"Testing port-forward health on port {local_port}")

        # Wait for port to become active (kubectl port-forward takes a moment to start)
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Try to connect to the port to see if it's active
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex(("localhost", local_port))
                    if result == 0:
                        # Connected (0) or connection refused (61) - both mean port-forward is working
                        self.debug_print(
                            f"Port-forward appears to be working on port {local_port} [green](result: {result})[/green]"
                        )
                        return True
                    elif result == 61:
                        self.debug_print(
                            f"Port-forward health check failed on port {local_port} [red](result: {result})[/red]"
                        )
                    else:
                        self.debug_print(
                            f"Port-forward health check failed on port {local_port} [red](result: {result})[/red]"
                        )
            except (OSError, socket.error):
                pass

            time.sleep(0.5)

        self.debug_print(
            f"Port-forward health check failed - port {local_port} not responding after {timeout}s"
        )
        return False

    def _test_socket_connectivity(self, local_port: int) -> Tuple[bool, str]:
        """Test basic socket connectivity to the port."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)  # Short timeout for connectivity check
                result = sock.connect_ex(("localhost", local_port))

                # Connection codes we consider successful:
                # 0 = Connected successfully
                # 61 (ECONNREFUSED) = Port is open but service refused connection (service may be down but port-forward works)
                if result == 0:
                    self.debug_print(
                        f"Socket connectivity test: Connected [green]successfully (code: {result})[/green]"
                    )
                    return True, "connected"
                elif result == 61:  # ECONNREFUSED on macOS/Linux
                    self.debug_print(
                        f"Socket connectivity test: Connection [red]refused - port-forward working, service may be down (code: {result})[/red]"
                    )
                    return (
                        False,
                        "connection_refused",
                    )  # Treated as failure to trigger restart if persistent
                else:
                    self.debug_print(f"Socket connectivity test failed (code: {result})")
                    return False, f"connection_error_{result}"

        except (OSError, socket.error) as e:
            self.debug_print(f"Socket connectivity test failed with exception: {e}")
            return False, f"socket_exception_{type(e).__name__}"

    def _is_non_http_protocol_error(self, error: Exception) -> bool:
        """Check if an error indicates the service uses a non-HTTP protocol (e.g., PostgreSQL, MySQL)."""
        error_str = str(error).lower()

        # Check for SSL errors that indicate non-HTTP protocols
        ssl_indicators = [
            "no application protocol",
            "tlsv1 alert no application protocol",
            "wrong version number",  # Common when non-HTTP service responds to HTTP
            "unknown protocol",  # Service doesn't speak HTTP
        ]

        # Check if it's an SSL error with non-HTTP indicators
        if isinstance(error, (SSLError, ssl.SSLError)):
            return any(indicator in error_str for indicator in ssl_indicators)

        # Check ConnectionError that might wrap SSL errors
        if isinstance(error, requests.exceptions.ConnectionError):
            # The error message often contains the underlying SSL error
            return any(indicator in error_str for indicator in ssl_indicators)

        return False

    def _test_http_connectivity(self, local_port: int) -> Tuple[ConnectivityTestResult, str]:
        """Test HTTP connectivity to the port."""
        current_time = time.time()

        # Rate limit HTTP requests
        if current_time - self.last_http_attempt_time < self.HTTP_RETRY_INTERVAL:
            self.debug_print("HTTP connectivity test rate limited")
            return ConnectivityTestResult.SUCCESS, "rate_limited"

        self.last_http_attempt_time = current_time

        # Try HTTP first (most common)
        urls = [f"http://localhost:{local_port}", f"https://localhost:{local_port}"]
        non_http_detected = False

        for url in urls:
            try:
                self.debug_print(f"Attempting HTTP connectivity test: {url}")

                # Make request with short timeout and disabled SSL verification
                response = requests.get(
                    url,
                    timeout=self.HTTP_TIMEOUT,
                    verify=False,  # Don't verify SSL for localhost
                    allow_redirects=False,  # Don't follow redirects for faster response
                )

                # Any HTTP response code is considered success
                self.debug_print(
                    f"HTTP connectivity test [green]successful: {url} -> {response.status_code}[/green]"
                )
                self._mark_http_timeout_end()  # Reset timeout tracking on success
                return (
                    ConnectivityTestResult.SUCCESS,
                    f"http_response_{response.status_code}",
                )

            except requests.exceptions.ConnectTimeout:
                self.debug_print(f"HTTP connectivity test [red]timeout: {url}[/red]")
                self._mark_http_timeout_start()  # Track timeout start
                continue  # Try next URL

            except requests.exceptions.ConnectionError as e:
                # Check if this is a non-HTTP protocol (e.g., database)
                if self._is_non_http_protocol_error(e):
                    non_http_detected = True
                    # Port is open but service doesn't speak HTTP - this is fine for port-forward health
                    self.debug_print(
                        f"Port {local_port} appears to use a non-HTTP protocol (e.g., database), skipping HTTP test"
                    )
                    # Don't try HTTPS if HTTP already detected non-HTTP protocol
                    break
                else:
                    self.debug_print(
                        f"HTTP connectivity test [red]connection error: {url} -> {e}[/red]"
                    )
                continue  # Try next URL

            except requests.exceptions.Timeout:
                self.debug_print(f"HTTP connectivity test [red]timeout: {url}[/red]")
                self._mark_http_timeout_start()  # Track timeout start
                continue  # Try next URL

            except SSLError as e:
                # Check if this is a non-HTTP protocol SSL error
                if self._is_non_http_protocol_error(e):
                    non_http_detected = True
                    self.debug_print(
                        f"Port {local_port} appears to use a non-HTTP protocol (e.g., database), skipping HTTP test"
                    )
                    break
                else:
                    self.debug_print(f"HTTP connectivity test [red]SSL error: {url} -> {e}[/red]")
                continue  # Try next URL

            except Exception as e:
                # Check if this is a non-HTTP protocol error
                if self._is_non_http_protocol_error(e):
                    non_http_detected = True
                    self.debug_print(
                        f"Port {local_port} appears to use a non-HTTP protocol (e.g., database), skipping HTTP test"
                    )
                    break
                else:
                    self.debug_print(
                        f"HTTP connectivity test [red]unexpected error: {url} -> {e}[/red]"
                    )
                continue  # Try next URL

        # If we detected a non-HTTP protocol, consider it success (port-forward is working)
        if non_http_detected:
            return ConnectivityTestResult.SUCCESS, "non_http_protocol_detected"

        # If we get here, all HTTP attempts failed
        return ConnectivityTestResult.HTTP_CONNECTION_ERROR, "all_http_attempts_failed"

    def check_port_connectivity(self, local_port: int) -> bool:
        """Check port-forward connectivity using socket and HTTP tests."""
        if not self.run_http_health_checks:
            self.debug_print("Health checks disabled, skipping connectivity check")
            return True  # Assume it's working when health checks are disabled

        if local_port is None:
            self.debug_print("No local port specified, skipping connectivity check")
            return True  # Can't test, assume it's working

        self.debug_print(
            f"Starting enhanced connectivity check for port {local_port}", rate_limit=True
        )

        # Step 1: Basic socket connectivity test
        socket_success, socket_description = self._test_socket_connectivity(local_port)

        if not socket_success:
            self.debug_print(f"Socket connectivity [red]failed: {socket_description}[/red]")
            self._mark_connectivity_failure(f"socket_failure: {socket_description}")
            return False

        self.debug_print(f"Socket connectivity [green]passed: {socket_description}[/green]")

        # Step 2: If socket connected successfully (not just refused), test HTTP
        if socket_description == "connected":
            http_result, http_description = self._test_http_connectivity(local_port)

            if http_result == ConnectivityTestResult.SUCCESS:
                self.debug_print(f"HTTP connectivity [green]passed: {http_description}[/green]")
                self._mark_connectivity_success()
                return True
            else:
                self.debug_print(f"HTTP connectivity [yellow]issue: {http_description}[/yellow]")
                # HTTP failure when socket works indicates service issues,
                # but we still consider the port-forward itself healthy.
                self._mark_connectivity_success()
                return True

        # If we are here, socket must have been refused (61) on mac/linux or similar
        return False
