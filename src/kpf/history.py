"""Frecency-based usage history for kpf.

Frecency (frequency × recency) ranks entries used both often and recently.
Score formula:  use_count / (1 + log2(age_hours + 1))

Log2 decay keeps recent items prominent without completely burying older ones.
No external dependency — the algorithm is a two-line formula.
"""

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class HistoryEntry:
    service: str
    namespace: str
    context: str
    local_port: int
    remote_port: int
    use_count: int
    last_used: float  # Unix timestamp
    frecency_score: float

    def to_port_forward_args(self) -> List[str]:
        """Return kubectl port-forward args to replay this session."""
        args = [
            f"svc/{self.service}",
            f"{self.local_port}:{self.remote_port}",
            "-n",
            self.namespace,
        ]
        if self.context:
            args.extend(["--context", self.context])
        return args

    @property
    def last_used_label(self) -> str:
        seconds = time.time() - self.last_used
        if seconds < 120:
            return "just now"
        minutes = seconds / 60
        if minutes < 60:
            return f"{int(minutes)}m ago"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)}h ago"
        days = hours / 24
        return f"{int(days)}d ago"

    @property
    def port_label(self) -> str:
        if self.local_port == self.remote_port:
            return str(self.local_port)
        return f"{self.local_port}:{self.remote_port}"


def load_history(folder: Path, limit: int = 20) -> List[HistoryEntry]:
    """Load and rank history entries from session JSON files using frecency scoring."""
    if not folder.exists():
        return []

    grouped: dict = {}

    for json_file in sorted(folder.glob("session_*.json"), reverse=True):
        try:
            with open(json_file) as f:
                data = json.load(f)

            service = data.get("service")
            namespace = data.get("namespace")
            local_port = data.get("local_port")
            remote_port = data.get("remote_port")
            context = data.get("context", "")
            start_time = data.get("start_time", 0.0)

            if not (service and namespace and local_port is not None and remote_port is not None):
                continue

            key = (service, namespace, local_port, remote_port)
            if key not in grouped:
                grouped[key] = {
                    "service": service,
                    "namespace": namespace,
                    "context": context,
                    "local_port": local_port,
                    "remote_port": remote_port,
                    "use_count": 0,
                    "last_used": 0.0,
                }

            grouped[key]["use_count"] += 1
            if float(start_time) > grouped[key]["last_used"]:
                grouped[key]["last_used"] = float(start_time)
                grouped[key]["context"] = context  # keep context from most recent session

        except Exception:
            continue

    now = time.time()
    entries: List[HistoryEntry] = []
    for item in grouped.values():
        age_hours = max(0.0, (now - item["last_used"]) / 3600)
        score = item["use_count"] / (1.0 + math.log2(age_hours + 1))
        entries.append(
            HistoryEntry(
                service=item["service"],
                namespace=item["namespace"],
                context=item["context"],
                local_port=int(item["local_port"]),
                remote_port=int(item["remote_port"]),
                use_count=item["use_count"],
                last_used=item["last_used"],
                frecency_score=score,
            )
        )

    entries.sort(key=lambda e: e.frecency_score, reverse=True)
    return entries[:limit]
