import subprocess
import threading
import time

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

from .connectivity import ConnectivityChecker
from .validators import extract_local_port

console = Console()


class PortForwarder:
    def __init__(
        self,
        port_forward_args,
        shutdown_event,
        restart_event,
        debug_callback=None,
        config=None,
        usage_logger=None,
        no_health_check: bool = False,
    ):
        self.port_forward_args = port_forward_args
        self.shutdown_event = shutdown_event
        self.restart_event = restart_event
        self.debug_print = debug_callback if debug_callback else lambda msg, rate_limit=False: None
        self.config = config
        self.usage_logger = usage_logger
        self.no_health_check = no_health_check

        self.local_port = extract_local_port(port_forward_args)
        self.connectivity_checker = ConnectivityChecker(
            debug_callback, run_http_health_checks=not no_health_check
        )

        # State
        self.last_restart_time = 0
        self.RESTART_THROTTLE_SECONDS = 5
        self.pending_restart = False

        # Reconnection config
        self.reconnect_attempts_made = 0
        if config:
            self.auto_reconnect = config.get("autoReconnect", True)
            self.max_reconnect_attempts = config.get("reconnectAttempts", 30)
            self.reconnect_delay = config.get("reconnectDelaySeconds", 5)
        else:
            self.auto_reconnect = True
            self.max_reconnect_attempts = 30
            self.reconnect_delay = 5

        self.thread = None

    def start(self):
        """Start the port-forwarder thread."""
        self.thread = threading.Thread(target=self.port_forward_thread)
        self.thread.start()

    def is_alive(self):
        return self.thread and self.thread.is_alive()

    def join(self, timeout=None):
        if self.thread:
            self.thread.join(timeout)

    def should_restart_port_forward(self):
        """Check if enough time has passed since last restart to allow another restart."""
        current_time = time.time()
        time_since_last_restart = current_time - self.last_restart_time

        if time_since_last_restart >= self.RESTART_THROTTLE_SECONDS:
            self.last_restart_time = current_time
            self.pending_restart = False  # Clear pending flag since we're restarting
            return True
        else:
            remaining_time = self.RESTART_THROTTLE_SECONDS - time_since_last_restart
            self.debug_print(f"[yellow]Restart throttled: {remaining_time:.1f}s remaining[/yellow]")
            self.pending_restart = True  # Mark that we need to restart later
            return False

    def check_pending_restart(self):
        """Check if there's a pending restart that can now be executed."""
        if self.pending_restart and self.should_restart_port_forward():
            self.debug_print("[green]Executing pending restart[/green]")
            return True
        return False

    def port_forward_thread(self):
        """
        This thread runs the kubectl port-forward command.
        It listens for the `restart_event` and restarts the process when it's set.
        It also monitors port connectivity every 5 seconds and restarts if connection fails.
        """
        self.debug_print(f"Port-forward thread started with args: {self.port_forward_args}")
        proc = None
        args = self.port_forward_args
        local_port = self.local_port
        first_run = True

        while not self.shutdown_event.is_set():
            try:
                # Track restarts (skip first run)
                if not first_run and self.usage_logger:
                    self.usage_logger.increment_restarts()
                first_run = False
                # Show direct command if configured (default: True)
                show_direct_command = True
                if self.config:
                    show_direct_command = self.config.get("showDirectCommand", True)

                if show_direct_command:
                    cmd_parts = ["kpf"] + args

                    # Add context if configured
                    if self.config and self.config.get("showDirectCommandIncludeContext", True):
                        from .kubernetes import KubernetesClient

                        k8s = KubernetesClient()
                        context = k8s.get_current_context()
                        if context:
                            cmd_parts.extend(["--context", context])

                    # Format as multiline if configured
                    if self.config and self.config.get("directCommandMultiLine", True):
                        formatted_cmd = "  kpf"
                        for i, part in enumerate(args):
                            if i == 0:
                                formatted_cmd += f" {part}"
                            elif part.startswith("-"):
                                formatted_cmd += f" \\\n      {part}"
                            else:
                                formatted_cmd += f" {part}"
                        # Add context at the end if present
                        if self.config.get("showDirectCommandIncludeContext", True):
                            from .kubernetes import KubernetesClient

                            k8s = KubernetesClient()
                            context = k8s.get_current_context()
                            if context:
                                formatted_cmd += f" \\\n      --context {context}"
                        console.print(f"\nDirect command:\n[cyan]{formatted_cmd}[/cyan]\n")
                    else:
                        console.print(f"\nDirect command: [cyan]{' '.join(cmd_parts)}[/cyan]\n")

                if local_port:
                    console.print(
                        f"[light_blue][link=http://localhost:{local_port}]http://localhost:{local_port}[/link][/light_blue]"
                    )

                self.debug_print(
                    f"\n[green][Port-Forwarder] Starting: kubectl port-forward {' '.join(args)}[/green]"
                )
                self.debug_print(f"Executing: kubectl port-forward {' '.join(args)}")
                proc = subprocess.Popen(
                    ["kubectl", "port-forward"] + args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.debug_print(f"Port-forward process started with PID: {proc.pid}")

                # Show connecting spinner while waiting for port-forward to start
                spinner = Spinner("dots", text="Connecting...")
                with Live(spinner, console=console, refresh_per_second=10):
                    # Give port-forward a moment to start
                    time.sleep(2)

                # Test if port-forward is healthy (skip if health checks disabled)
                if not self.no_health_check:
                    if not self.connectivity_checker.test_port_forward_health(local_port):
                        console.print("[red]Port-forward failed to start properly[/red]")
                        console.print(
                            "[yellow]This may indicate the service is not running or the port mapping is incorrect[/yellow]"
                        )
                        if proc:
                            self.debug_print(
                                f"Terminating failed port-forward process PID: {proc.pid}"
                            )
                            self._kill_proc(proc)

                        # Instead of shutting down immediately, set restart event to try again
                        console.print("[yellow]Will retry port-forward in a moment...[/yellow]")
                        self.restart_event.set()
                        continue

                console.print("\n🚀 [green]port-forward started[/green] 🚀")

                # Main loop: wait for restart signal or shutdown, checking connectivity periodically
                last_connectivity_check = time.time()

                while not self.restart_event.is_set() and not self.shutdown_event.is_set():
                    current_time = time.time()

                    # Check if it's time to test connectivity (minimum 2 seconds between checks)
                    # Skip connectivity checks if health checks are disabled
                    if (
                        not self.no_health_check
                        and current_time - last_connectivity_check
                        >= self.connectivity_checker.CONNECTIVITY_CHECK_INTERVAL
                    ):
                        self.debug_print(
                            f"Checking port connectivity on port {local_port}",
                            rate_limit=True,
                        )

                        if not self.connectivity_checker.check_port_connectivity(local_port):
                            failure_duration = (
                                self.connectivity_checker.get_connectivity_failure_duration()
                            )
                            console.print(
                                f"[red]Port-forward connection failed on port {local_port}[/red]"
                            )
                            console.print(
                                f"[yellow]Failed to establish a new connection (failing for {failure_duration:.1f}s)[/yellow]"
                            )

                            # Check if we've been failing for too long
                            if self.connectivity_checker.check_connectivity_failure_timeout():
                                console.print(
                                    f"[red]Port-forward has been failing for {self.connectivity_checker.CONNECTIVITY_FAILURE_TIMEOUT}+ seconds[/red]"
                                )
                                console.print(
                                    "[red]This usually indicates one of the following:[/red]"
                                )
                                console.print(
                                    "[red]  • kubectl port-forward process died unexpectedly[/red]"
                                )
                                console.print(
                                    "[red]  • Target service/pod is no longer available[/red]"
                                )
                                console.print(
                                    "[red]  • Network connectivity issues to Kubernetes cluster[/red]"
                                )
                                console.print(
                                    f"[red]  • Port {local_port} is being blocked or intercepted[/red]"
                                )

                                # Check auto-reconnect settings
                                if not self.auto_reconnect:
                                    console.print(
                                        "[yellow]Auto-reconnect is disabled, exiting[/yellow]"
                                    )
                                    self.shutdown_event.set()
                                    return

                                self.reconnect_attempts_made += 1
                                if self.usage_logger:
                                    self.usage_logger.increment_reconnect_attempts()

                                if self.reconnect_attempts_made >= self.max_reconnect_attempts:
                                    console.print(
                                        f"[red]Max reconnection attempts ({self.max_reconnect_attempts}) reached[/red]"
                                    )
                                    console.print(
                                        "[yellow]Exiting kpf. Please check your service and cluster status.[/yellow]"
                                    )
                                    self.shutdown_event.set()
                                    return

                                console.print(
                                    f"[yellow]Reconnection attempt {self.reconnect_attempts_made}/{self.max_reconnect_attempts}[/yellow]"
                                )
                                console.print(
                                    f"[yellow]Waiting {self.reconnect_delay}s before reconnecting...[/yellow]"
                                )

                                # Interruptible sleep
                                for _ in range(self.reconnect_delay):
                                    if self.shutdown_event.is_set():
                                        return
                                    time.sleep(1)

                                if self.should_restart_port_forward():
                                    self.restart_event.set()
                                    break
                                return

                            # Check if we should restart (throttling)
                            if self.should_restart_port_forward():
                                self.restart_event.set()
                                break
                            else:
                                console.print(
                                    f"[yellow]Restart throttled, will retry connectivity check in {self.connectivity_checker.CONNECTIVITY_CHECK_INTERVAL}s[/yellow]"
                                )
                        else:
                            # Reset reconnect attempts on successful connection
                            if self.reconnect_attempts_made > 0:
                                console.print(
                                    "[green]Connection restored, resetting reconnect counter[/green]"
                                )
                                self.reconnect_attempts_made = 0

                            self.debug_print(
                                f"Port connectivity check passed on port {local_port}",
                                rate_limit=True,
                            )

                        # Check if HTTP timeouts have persisted for too long and trigger restart
                        if (
                            not self.no_health_check
                            and self.connectivity_checker.check_http_timeout_restart()
                        ):
                            console.print(
                                "[yellow]HTTP connectivity timeouts persisting, restarting port-forward[/yellow]"
                            )
                            if self.should_restart_port_forward():
                                self.restart_event.set()
                                break
                            else:
                                console.print(
                                    f"[yellow]Restart throttled, will retry connectivity check in {self.connectivity_checker.CONNECTIVITY_CHECK_INTERVAL}s[/yellow]"
                                )

                        # Update last connectivity check time
                        last_connectivity_check = current_time

                    # Check if there's a pending restart that can now be executed
                    if self.check_pending_restart():
                        console.print(
                            "[green][Port-Forwarder] Executing pending restart due to endpoint changes[/green]"
                        )
                        self.restart_event.set()
                        break

                    time.sleep(1.0)  # Sleep for 1 second between loop iterations

                if proc and (self.restart_event.is_set() or self.shutdown_event.is_set()):
                    if self.restart_event.is_set():
                        console.print(
                            "[yellow][Port-Forwarder] Endpoint change detected, restarting port-forward process...[/yellow]"
                        )
                    self.debug_print(f"Terminating port-forward process PID: {proc.pid}")
                    self._kill_proc(proc)
                    proc = None

                self.restart_event.clear()  # Reset the event for the next cycle

            except Exception as e:
                console.print(f"[red][Port-Forwarder] An error occurred: {e}[/red]")
                if proc:
                    self._kill_proc(proc)
                self.shutdown_event.set()
                return

        if proc:
            self.debug_print("Final cleanup: terminating port-forward process")
            self._kill_proc(proc)

    def _kill_proc(self, proc):
        if not proc:
            return
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
