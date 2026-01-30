"""
Tests for retention cleanup job: dry-run, batch size, delete and mark deleted.

TECH_SPEC_V1.1.md. Uses mocked DB and config; no real file deletion.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from worker.cleanup import run_retention_cleanup


def _config(
    batch_size: int = 100,
    dry_run: bool = False,
    artifacts_dir: str = "/tmp/artifacts",
) -> SimpleNamespace:
    return SimpleNamespace(
        retention_cleanup_batch_size=batch_size,
        retention_cleanup_dry_run=dry_run,
        artifacts_dir=artifacts_dir,
    )


def _artifact(artifact_id=None, session_id=None, storage_uri=None, size_bytes=1024):
    return {
        "id": artifact_id or uuid4(),
        "session_id": session_id or uuid4(),
        "storage_uri": storage_uri or "sess/page/viewport/html_gz.html.gz",
        "size_bytes": size_bytes,
    }


def _mock_db_session(session):
    """Return a context manager mock that yields session."""
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = None
    return cm


@patch("worker.cleanup.get_db_session")
@patch("worker.cleanup.get_config")
def test_dry_run_logs_candidates_without_deleting(mock_config, mock_db_session):
    """Dry-run mode: logs candidates, does not call mark_artifact_deleted or unlink."""
    mock_config.return_value = _config(dry_run=True)
    repo = MagicMock()
    repo.get_expired_html_artifacts.return_value = [
        _artifact(storage_uri="a/1.html.gz", size_bytes=100),
        _artifact(storage_uri="b/2.html.gz", size_bytes=200),
    ]
    session = MagicMock()
    mock_db_session.return_value = _mock_db_session(session)

    with patch("worker.cleanup.AuditRepository", return_value=repo):
        result = run_retention_cleanup()

    repo.get_expired_html_artifacts.assert_called_once_with(100)
    repo.mark_artifact_deleted.assert_not_called()
    assert result["deleted"] == 2
    assert result["failed"] == 0
    assert result["reclaimed_bytes"] == 300


@patch("worker.cleanup.get_db_session")
@patch("worker.cleanup.get_config")
def test_not_dry_run_deletes_and_marks(mock_config, mock_db_session):
    """When not dry-run: unlinks file and marks artifact deleted."""
    aid, sid = uuid4(), uuid4()
    mock_config.return_value = _config(dry_run=False, artifacts_dir="/art")
    repo = MagicMock()
    repo.get_expired_html_artifacts.return_value = [
        _artifact(artifact_id=aid, session_id=sid, storage_uri="s/p/v/html_gz.html.gz"),
    ]
    session = MagicMock()
    mock_db_session.return_value = _mock_db_session(session)

    with patch("worker.cleanup.AuditRepository", return_value=repo):
        with patch("worker.cleanup.Path") as mock_path_class:
            mock_path = MagicMock()
            mock_path_class.return_value.__truediv__.return_value = mock_path
            result = run_retention_cleanup()

    repo.mark_artifact_deleted.assert_called_once()
    call_arg = repo.mark_artifact_deleted.call_args[0][0]
    assert str(call_arg) == str(aid)
    mock_path.unlink.assert_called_once_with(missing_ok=True)
    assert result["deleted"] == 1
    assert result["failed"] == 0


@patch("worker.cleanup.get_db_session")
@patch("worker.cleanup.get_config")
def test_batch_size_from_config(mock_config, mock_db_session):
    """Batch size is passed from config to get_expired_html_artifacts."""
    mock_config.return_value = _config(batch_size=50)
    repo = MagicMock()
    repo.get_expired_html_artifacts.return_value = []
    session = MagicMock()
    mock_db_session.return_value = _mock_db_session(session)

    with patch("worker.cleanup.AuditRepository", return_value=repo):
        run_retention_cleanup()

    repo.get_expired_html_artifacts.assert_called_once_with(50)


@patch("worker.cleanup.get_db_session")
@patch("worker.cleanup.get_config")
def test_cleanup_returns_deleted_failed_reclaimed(mock_config, mock_db_session):
    """Return dict includes deleted, failed, reclaimed_bytes."""
    mock_config.return_value = _config(dry_run=True)
    repo = MagicMock()
    repo.get_expired_html_artifacts.return_value = []
    session = MagicMock()
    mock_db_session.return_value = _mock_db_session(session)

    with patch("worker.cleanup.AuditRepository", return_value=repo):
        result = run_retention_cleanup()

    assert "deleted" in result
    assert "failed" in result
    assert "reclaimed_bytes" in result
    assert result["deleted"] == 0
    assert result["reclaimed_bytes"] == 0


@patch("worker.cleanup.get_db_session")
@patch("worker.cleanup.get_config")
def test_failure_increments_failed_count(mock_config, mock_db_session):
    """When delete or mark fails, failed_count increments and processing continues."""
    aid = uuid4()
    mock_config.return_value = _config(dry_run=False)
    repo = MagicMock()
    repo.get_expired_html_artifacts.return_value = [
        _artifact(artifact_id=aid, storage_uri="fail/html_gz.html.gz"),
    ]
    repo.mark_artifact_deleted.side_effect = RuntimeError("db error")
    session = MagicMock()
    mock_db_session.return_value = _mock_db_session(session)

    with patch("worker.cleanup.AuditRepository", return_value=repo):
        with patch("worker.cleanup.Path"):
            result = run_retention_cleanup()

    assert result["deleted"] == 0
    assert result["failed"] == 1
    assert result["reclaimed_bytes"] == 0


@patch("worker.cleanup.get_db_session")
@patch("worker.cleanup.get_config")
def test_empty_expired_completes_with_zero_counts(mock_config, mock_db_session):
    """No expired artifacts: deleted=0, failed=0, reclaimed_bytes=0."""
    mock_config.return_value = _config()
    repo = MagicMock()
    repo.get_expired_html_artifacts.return_value = []
    session = MagicMock()
    mock_db_session.return_value = _mock_db_session(session)

    with patch("worker.cleanup.AuditRepository", return_value=repo):
        result = run_retention_cleanup()

    assert result["deleted"] == 0
    assert result["failed"] == 0
    assert result["reclaimed_bytes"] == 0
