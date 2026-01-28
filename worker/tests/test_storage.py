"""
Unit tests for artifact storage path building.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from worker.storage import build_artifact_path


def test_build_artifact_path_screenshot():
    """Test path building for screenshot artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "screenshot")

    assert path.name == "screenshot.png"
    assert str(session_id) in str(path)
    assert "homepage" in str(path)
    assert "desktop" in str(path)


def test_build_artifact_path_visible_text():
    """Test path building for visible text artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "mobile", "visible_text")

    assert path.name == "visible_text.txt"
    assert str(session_id) in str(path)
    assert "homepage" in str(path)
    assert "mobile" in str(path)


def test_build_artifact_path_features_json():
    """Test path building for features JSON artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "features_json")

    assert path.name == "features_json.json"
    assert str(session_id) in str(path)


def test_build_artifact_path_html_gz():
    """Test path building for HTML gzip artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "mobile", "html_gz")

    assert path.name == "html_gz.html.gz"
    assert str(session_id) in str(path)


def test_build_artifact_path_structure():
    """Test that path follows the expected directory structure."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "screenshot")

    parts = path.parts
    # Should be: <root>/<session_id>/homepage/desktop/screenshot.png
    assert parts[-1] == "screenshot.png"
    assert parts[-2] == "desktop"
    assert parts[-3] == "homepage"
    assert parts[-4] == str(session_id)
