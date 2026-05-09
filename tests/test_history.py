"""Tests for history module."""

import json
import time

from src.kpf.history import HistoryEntry, load_history


class TestHistoryEntry:
    def test_port_label_same(self):
        entry = HistoryEntry("svc", "ns", "", 8080, 8080, 1, time.time(), 1.0)
        assert entry.port_label == "8080"

    def test_port_label_different(self):
        entry = HistoryEntry("svc", "ns", "", 9090, 8080, 1, time.time(), 1.0)
        assert entry.port_label == "9090:8080"

    def test_to_port_forward_args_no_context(self):
        entry = HistoryEntry("my-svc", "production", "", 8080, 8080, 1, time.time(), 1.0)
        assert entry.to_port_forward_args() == ["svc/my-svc", "8080:8080", "-n", "production"]

    def test_to_port_forward_args_with_context(self):
        entry = HistoryEntry("my-svc", "production", "my-cluster", 8080, 8080, 1, time.time(), 1.0)
        assert entry.to_port_forward_args() == [
            "svc/my-svc",
            "8080:8080",
            "-n",
            "production",
            "--context",
            "my-cluster",
        ]

    def test_last_used_label_just_now(self):
        entry = HistoryEntry("svc", "ns", "", 8080, 8080, 1, time.time(), 1.0)
        assert entry.last_used_label == "just now"

    def test_last_used_label_minutes(self):
        entry = HistoryEntry("svc", "ns", "", 8080, 8080, 1, time.time() - 300, 1.0)
        assert entry.last_used_label == "5m ago"

    def test_last_used_label_hours(self):
        entry = HistoryEntry("svc", "ns", "", 8080, 8080, 1, time.time() - 7200, 1.0)
        assert entry.last_used_label == "2h ago"

    def test_last_used_label_days(self):
        entry = HistoryEntry("svc", "ns", "", 8080, 8080, 1, time.time() - 86400 * 3, 1.0)
        assert entry.last_used_label == "3d ago"


class TestLoadHistory:
    def test_empty_folder(self, tmp_path):
        assert load_history(tmp_path) == []

    def test_nonexistent_folder(self, tmp_path):
        assert load_history(tmp_path / "nonexistent") == []

    def test_loads_single_session(self, tmp_path):
        session = {
            "service": "frontend",
            "namespace": "default",
            "context": "my-cluster",
            "local_port": 8080,
            "remote_port": 8080,
            "start_time": time.time() - 60,
        }
        (tmp_path / "session_20260101_120000.json").write_text(json.dumps(session))

        entries = load_history(tmp_path)
        assert len(entries) == 1
        assert entries[0].service == "frontend"
        assert entries[0].namespace == "default"
        assert entries[0].use_count == 1

    def test_deduplicates_same_service(self, tmp_path):
        now = time.time()
        for i in range(3):
            session = {
                "service": "frontend",
                "namespace": "default",
                "context": "my-cluster",
                "local_port": 8080,
                "remote_port": 8080,
                "start_time": now - i * 60,
            }
            (tmp_path / f"session_2026010{i}_120000.json").write_text(json.dumps(session))

        entries = load_history(tmp_path)
        assert len(entries) == 1
        assert entries[0].use_count == 3

    def test_frecency_ranks_frequent_recent_first(self, tmp_path):
        now = time.time()
        # Write 5 sessions for "frequent-svc" (high count, recent)
        for i in range(5):
            session = {
                "service": "frequent-svc",
                "namespace": "default",
                "context": "",
                "local_port": 9000,
                "remote_port": 9000,
                "start_time": now - i * 60,
            }
            (tmp_path / f"session_frequent_{i}.json").write_text(json.dumps(session))

        # Write 1 session for "rare-svc" (used once, long ago)
        session = {
            "service": "rare-svc",
            "namespace": "default",
            "context": "",
            "local_port": 9001,
            "remote_port": 9001,
            "start_time": now - 86400 * 30,  # 30 days ago
        }
        (tmp_path / "session_rare.json").write_text(json.dumps(session))

        entries = load_history(tmp_path)
        assert entries[0].service == "frequent-svc"
        assert entries[1].service == "rare-svc"

    def test_respects_limit(self, tmp_path):
        now = time.time()
        for i in range(25):
            session = {
                "service": f"svc-{i}",
                "namespace": "default",
                "context": "",
                "local_port": 8000 + i,
                "remote_port": 8000 + i,
                "start_time": now - i,
            }
            (tmp_path / f"session_{i:04d}.json").write_text(json.dumps(session))

        entries = load_history(tmp_path, limit=10)
        assert len(entries) == 10

    def test_skips_malformed_files(self, tmp_path):
        (tmp_path / "session_bad.json").write_text("not json{{{")
        valid = {
            "service": "ok-svc",
            "namespace": "default",
            "context": "",
            "local_port": 8080,
            "remote_port": 8080,
            "start_time": time.time(),
        }
        (tmp_path / "session_good.json").write_text(json.dumps(valid))

        entries = load_history(tmp_path)
        assert len(entries) == 1
        assert entries[0].service == "ok-svc"

    def test_skips_incomplete_sessions(self, tmp_path):
        incomplete = {"service": "svc-no-ports", "namespace": "default"}
        (tmp_path / "session_incomplete.json").write_text(json.dumps(incomplete))

        assert load_history(tmp_path) == []
