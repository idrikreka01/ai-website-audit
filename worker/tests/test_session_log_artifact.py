"""
Tests for session log artifact: get_logs_by_session_id, save_session_logs, export at job end.

TECH_SPEC v1.20: session_logs_jsonl artifact; export at end of every job;
failure must not alter session status.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from worker.artifacts import save_session_logs
from worker.storage import write_jsonl


def _config(artifacts_dir: str) -> SimpleNamespace:
    return SimpleNamespace(artifacts_dir=artifacts_dir)


def test_save_session_logs_success_writes_jsonl_and_creates_artifact():
    """save_session_logs writes session_logs.jsonl and creates artifact (correct type and URI)."""
    session_id = uuid4()
    domain = "example.com"
    logs = [
        {
            "id": 1,
            "session_id": session_id,
            "level": "info",
            "event_type": "navigation",
            "message": "Loaded",
            "details": {},
            "timestamp": "2025-01-01T12:00:00+00:00",
        },
    ]

    repo = MagicMock()
    repo.get_logs_by_session_id.return_value = logs

    # Use workspace dir so sandbox allows the write
    with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmpdir:
        cfg = _config(tmpdir)
        with (
            patch("worker.storage.get_config", return_value=cfg),
            patch("worker.artifacts.get_config", return_value=cfg),
        ):
            result = save_session_logs(repo, session_id, domain)

        assert result is True
        repo.get_logs_by_session_id.assert_called_once_with(session_id)
        repo.create_artifact.assert_called_once()
        call_kw = repo.create_artifact.call_args.kwargs
        assert call_kw["session_id"] == session_id
        assert call_kw["page_id"] is None
        assert call_kw["artifact_type"] == "session_logs_jsonl"
        assert "session_logs.jsonl" in call_kw["storage_uri"]
        assert call_kw["storage_uri"].startswith(f"{domain}__{session_id}")
        assert call_kw["size_bytes"] > 0
        assert call_kw["checksum"] is not None
        repo.create_log.assert_not_called()

        # File was written under artifacts_dir (assert before tmpdir is cleaned up)
        path = Path(tmpdir) / f"{domain}__{session_id}" / "session_logs.jsonl"
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        assert "Loaded" in json.loads(lines[0])["message"]


def test_save_session_logs_failure_returns_false_and_logs():
    """On failure, save_session_logs returns False, logs error, does not raise."""
    session_id = uuid4()
    domain = "example.com"
    repo = MagicMock()
    repo.get_logs_by_session_id.side_effect = RuntimeError("DB error")

    with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmpdir:
        cfg = _config(tmpdir)
        with (
            patch("worker.storage.get_config", return_value=cfg),
            patch("worker.artifacts.get_config", return_value=cfg),
        ):
            result = save_session_logs(repo, session_id, domain)

    assert result is False
    repo.create_artifact.assert_not_called()
    repo.create_log.assert_called_once()
    log_call = repo.create_log.call_args.kwargs
    assert log_call["level"] == "error"
    assert log_call["event_type"] == "artifact"
    assert "Session log export failed" in log_call["message"]
    assert "session_logs_jsonl" in log_call["details"]["artifact_type"]


def test_save_session_logs_write_failure_returns_false():
    """When write_jsonl fails (e.g. permission), save_session_logs returns False."""
    session_id = uuid4()
    domain = "example.com"
    logs = [{"id": 1, "message": "x"}]
    repo = MagicMock()
    repo.get_logs_by_session_id.return_value = logs

    with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmpdir:
        cfg = _config(tmpdir)
        with (
            patch("worker.storage.get_config", return_value=cfg),
            patch("worker.artifacts.get_config", return_value=cfg),
            patch("worker.artifacts.write_jsonl", side_effect=OSError("Permission denied")),
        ):
            result = save_session_logs(repo, session_id, domain)

    assert result is False
    repo.create_artifact.assert_not_called()
    repo.create_log.assert_called_once()


def test_write_jsonl_serializes_datetime_and_uuid():
    """write_jsonl serializes datetime and UUID in rows."""
    with tempfile.TemporaryDirectory(dir=os.getcwd()) as tmpdir:
        path = Path(tmpdir) / "out.jsonl"
        from datetime import datetime, timezone

        rows = [
            {
                "id": 1,
                "session_id": uuid4(),
                "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                "message": "test",
            },
        ]
        size, checksum = write_jsonl(path, rows)
        assert size > 0
        assert checksum is not None
        content = path.read_text()
        assert "2025-01-01" in content
        assert "test" in content
