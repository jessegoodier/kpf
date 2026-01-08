"""Usage logging for kpf sessions."""

import json
import time
from datetime import datetime
from pathlib import Path


class UsageLogger:
    """Logger for tracking kpf session usage details."""

    def __init__(self, config=None):
        """Initialize usage logger.

        Args:
            config: Optional config dict with captureUsageDetails and usageDetailFolder
        """
        self.enabled = config.get("captureUsageDetails", False) if config else False

        if self.enabled:
            folder = config.get("usageDetailFolder", "~/.config/kpf/usage-details")
            self.folder = Path(folder).expanduser()
        else:
            self.folder = None

        self.session_data = {
            "start_time": time.time(),
            "start_time_iso": datetime.now().isoformat(),
            "service": None,
            "namespace": None,
            "context": None,
            "local_port": None,
            "remote_port": None,
            "restarts": 0,
            "endpoint_changes": 0,
            "reconnect_attempts": 0,
            "exit_reason": None,
        }

    def set_session_info(self, service, namespace, context, local_port, remote_port):
        """Set session information for logging.

        Args:
            service: Service name
            namespace: Kubernetes namespace
            context: Kubernetes context
            local_port: Local port number
            remote_port: Remote port number
        """
        if self.enabled:
            self.session_data.update(
                {
                    "service": service,
                    "namespace": namespace,
                    "context": context,
                    "local_port": local_port,
                    "remote_port": remote_port,
                }
            )

    def increment_restarts(self):
        """Increment the restart counter."""
        if self.enabled:
            self.session_data["restarts"] += 1

    def increment_endpoint_changes(self):
        """Increment the endpoint change counter."""
        if self.enabled:
            self.session_data["endpoint_changes"] += 1

    def increment_reconnect_attempts(self):
        """Increment the reconnect attempt counter."""
        if self.enabled:
            self.session_data["reconnect_attempts"] += 1

    def finalize(self, exit_reason: str):
        """Finalize the session and write log to disk.

        Args:
            exit_reason: Reason for session exit (e.g., 'user_interrupt', 'error', 'normal_exit')
        """
        if not self.enabled or not self.folder:
            return

        self.session_data["exit_reason"] = exit_reason
        self.session_data["end_time"] = time.time()
        self.session_data["end_time_iso"] = datetime.now().isoformat()
        self.session_data["duration_seconds"] = (
            self.session_data["end_time"] - self.session_data["start_time"]
        )

        self._write_log()

    def _write_log(self):
        """Write the session log to a JSON file."""
        if not self.folder:
            return

        try:
            self.folder.mkdir(parents=True, exist_ok=True)

            # Use timestamp for filename
            filename = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = self.folder / filename

            with open(filepath, "w") as f:
                json.dump(self.session_data, f, indent=2)

        except Exception as e:
            # Don't crash on logging errors, just print warning
            from rich.console import Console

            console = Console()
            console.print(f"[yellow]Warning: Failed to write usage log: {e}[/yellow]")
