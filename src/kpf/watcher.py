import subprocess
import threading
import time

from rich.console import Console

console = Console()


class EndpointWatcher:
    def __init__(
        self,
        namespace,
        resource_name,
        shutdown_event,
        restart_event,
        delegate_should_restart,
        debug_callback=None,
        usage_logger=None,
    ):
        self.namespace = namespace
        self.resource_name = resource_name
        self.shutdown_event = shutdown_event
        self.restart_event = restart_event
        self.delegate_should_restart = (
            delegate_should_restart  # Function to check if we can restart
        )
        self.debug_print = debug_callback if debug_callback else lambda msg, rate_limit=False: None
        self.usage_logger = usage_logger
        self.thread = None

    def start(self):
        """Start the watcher thread."""
        self.thread = threading.Thread(target=self.endpoint_watcher_thread)
        self.thread.start()

    def is_alive(self):
        return self.thread and self.thread.is_alive()

    def join(self, timeout=None):
        if self.thread:
            self.thread.join(timeout)

    def endpoint_watcher_thread(self):
        """
        This thread watches the specified endpoint for changes.
        When a change is detected, it sets the `restart_event`.
        """
        self.debug_print(
            f"Endpoint watcher thread started for {self.namespace}/{self.resource_name}"
        )
        proc = None
        while not self.shutdown_event.is_set():
            try:
                self.debug_print(
                    f"[green][Watcher] Starting watcher for endpoint changes for '{self.namespace}/{self.resource_name}'...[/green]"
                )
                command = [
                    "kubectl",
                    "get",
                    "--no-headers",
                    "ep",
                    "-w",
                    "-n",
                    self.namespace,
                    self.resource_name,
                ]
                self.debug_print(
                    f"Executing endpoint watcher command: {' '.join(command)}",
                    rate_limit=True,
                )

                proc = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                )
                self.debug_print(f"Endpoint watcher process started with PID: {proc.pid}")

                # The `for` loop will block and yield lines as they are produced
                # by the subprocess's stdout.
                is_first_line = True
                for line in proc.stdout:
                    if self.shutdown_event.is_set():
                        self.debug_print("Shutdown event detected in endpoint watcher, breaking")
                        break
                    self.debug_print(
                        f"Endpoint watcher received line: {line.strip()}", rate_limit=True
                    )
                    # The first line is the table header, which we should ignore.
                    if is_first_line:
                        is_first_line = False
                        self.debug_print("Skipping first line (header)")
                        continue
                    else:
                        self.debug_print("Endpoint change detected")
                        self.debug_print(f"Endpoint change details: {line.strip()}")

                        # Check if we should restart (throttling)
                        if self.delegate_should_restart():
                            console.print(
                                "[green][Watcher] Endpoint change detected, restarting port-forward...[/green]"
                            )
                            if self.usage_logger:
                                self.usage_logger.increment_endpoint_changes()
                            self.restart_event.set()
                        else:
                            self.debug_print(
                                "[Watcher] Endpoint change detected, but restart throttled"
                            )

                # If the subprocess finishes, we should break out and restart the watcher
                # This handles cases where the kubectl process itself might terminate.
                proc.wait()

                # Add delay before restarting to prevent rapid kubectl process creation
                if not self.shutdown_event.is_set():
                    self.debug_print(
                        "Endpoint watcher kubectl process ended, waiting 2s before restart",
                        rate_limit=True,
                    )
                    time.sleep(2)

            except Exception as e:
                console.print(f"[red][Watcher] An error occurred: {e}[/red]")
                if proc:
                    self._kill_proc(proc)

                self.shutdown_event.set()
                return

        if proc:
            self.debug_print("Final cleanup: terminating endpoint watcher process")
            self._kill_proc(proc)

    def _kill_proc(self, proc):
        if not proc:
            return
        proc.terminate()
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
