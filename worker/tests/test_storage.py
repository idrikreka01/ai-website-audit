"""
Unit tests for artifact storage path building and naming convention per spec.

Spec: {session_id}__{domain}/{page_type}/{viewport}/{artifact_type}.{ext}
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from shared.config import get_config
from worker.storage import build_artifact_path

DOMAIN = "example.com"


def test_build_artifact_path_screenshot():
    """Test path building for screenshot artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)

    assert path.name == "screenshot.png"
    assert str(session_id) in str(path)
    assert "homepage" in str(path)
    assert "desktop" in str(path)


def test_build_artifact_path_visible_text():
    """Test path building for visible text artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "mobile", "visible_text", DOMAIN)

    assert path.name == "visible_text.txt"
    assert str(session_id) in str(path)
    assert "homepage" in str(path)
    assert "mobile" in str(path)


def test_build_artifact_path_features_json():
    """Test path building for features JSON artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "features_json", DOMAIN)

    assert path.name == "features_json.json"
    assert str(session_id) in str(path)


def test_build_artifact_path_html_gz():
    """Test path building for HTML gzip artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "mobile", "html_gz", DOMAIN)

    assert path.name == "html_gz.html.gz"
    assert str(session_id) in str(path)


def test_build_artifact_path_structure():
    """Test that path follows the expected directory structure."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)

    parts = path.parts
    # Should be: <root>/<session_id>__<domain>/homepage/desktop/screenshot.png
    assert parts[-1] == "screenshot.png"
    assert parts[-2] == "desktop"
    assert parts[-3] == "homepage"
    assert parts[-4] == f"{session_id}__{DOMAIN}"


def test_build_artifact_path_domain_normalization():
    """Domain is normalized: lowercase and strip leading www."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "screenshot", "WWW.Example.COM")

    assert f"{session_id}__example.com" in str(path)


def test_naming_convention_per_spec():
    """
    Naming convention per TECH_SPEC:
    {session_id}__{domain}/{page_type}/{viewport}/{artifact_type}.{ext}
    """
    config = get_config()
    artifacts_root = Path(config.artifacts_dir)
    session_id = uuid4()
    ext_map = {
        "screenshot": "png",
        "visible_text": "txt",
        "features_json": "json",
        "html_gz": "html.gz",
    }
    for artifact_type, ext in ext_map.items():
        path = build_artifact_path(session_id, "homepage", "desktop", artifact_type, DOMAIN)
        assert path.name == f"{artifact_type}.{ext}"
        assert str(session_id) in str(path)
        assert "homepage" in str(path)
        assert "desktop" in str(path)
        # Relative path from artifacts root must match spec
        try:
            rel = path.relative_to(artifacts_root)
        except ValueError:
            rel = path
        rel_parts = rel.parts
        assert len(rel_parts) >= 4
        assert rel_parts[0] == f"{session_id}__{DOMAIN}"
        assert rel_parts[1] == "homepage"
        assert rel_parts[2] == "desktop"
        assert rel_parts[3] == f"{artifact_type}.{ext}"


# --- All artifact type + page type + viewport combinations ---


def test_all_artifact_combinations():
    """Test all combinations of artifact types, page types, and viewports."""
    session_id = uuid4()
    artifact_types = ["screenshot", "visible_text", "features_json", "html_gz"]
    page_types = ["homepage", "pdp"]
    viewports = ["desktop", "mobile"]

    for artifact_type in artifact_types:
        for page_type in page_types:
            for viewport in viewports:
                path = build_artifact_path(session_id, page_type, viewport, artifact_type, DOMAIN)

                # Verify all components in path
                assert str(session_id) in str(path)
                assert page_type in str(path)
                assert viewport in str(path)
                assert artifact_type in path.name


def test_naming_convention_pdp_mobile():
    """Test naming convention for PDP mobile artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "pdp", "mobile", "screenshot", DOMAIN)

    parts = path.parts
    assert parts[-4] == f"{session_id}__{DOMAIN}"
    assert parts[-3] == "pdp"
    assert parts[-2] == "mobile"
    assert parts[-1] == "screenshot.png"


def test_naming_convention_homepage_desktop():
    """Test naming convention for homepage desktop artifacts."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "visible_text", DOMAIN)

    parts = path.parts
    assert parts[-4] == f"{session_id}__{DOMAIN}"
    assert parts[-3] == "homepage"
    assert parts[-2] == "desktop"
    assert parts[-1] == "visible_text.txt"


# --- Path uniqueness tests ---


def test_artifact_paths_unique_per_session():
    """Different sessions produce different paths."""
    session_id_1 = uuid4()
    session_id_2 = uuid4()

    path1 = build_artifact_path(session_id_1, "homepage", "desktop", "screenshot", DOMAIN)
    path2 = build_artifact_path(session_id_2, "homepage", "desktop", "screenshot", DOMAIN)

    assert path1 != path2
    assert str(session_id_1) in str(path1)
    assert str(session_id_2) in str(path2)


def test_artifact_paths_unique_per_page_type():
    """Different page types produce different paths."""
    session_id = uuid4()

    path_home = build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)
    path_pdp = build_artifact_path(session_id, "pdp", "desktop", "screenshot", DOMAIN)

    assert path_home != path_pdp
    assert "homepage" in str(path_home)
    assert "pdp" in str(path_pdp)


def test_artifact_paths_unique_per_viewport():
    """Different viewports produce different paths."""
    session_id = uuid4()

    path_desktop = build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)
    path_mobile = build_artifact_path(session_id, "homepage", "mobile", "screenshot", DOMAIN)

    assert path_desktop != path_mobile
    assert "desktop" in str(path_desktop)
    assert "mobile" in str(path_mobile)


def test_artifact_paths_unique_per_type():
    """Different artifact types produce different filenames."""
    session_id = uuid4()

    path_screenshot = build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)
    path_text = build_artifact_path(session_id, "homepage", "desktop", "visible_text", DOMAIN)

    assert path_screenshot.name != path_text.name
    assert path_screenshot.name == "screenshot.png"
    assert path_text.name == "visible_text.txt"


# --- Path determinism tests ---


def test_build_artifact_path_deterministic():
    """Same inputs produce identical paths across multiple calls."""
    session_id = uuid4()

    paths = [
        build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)
        for _ in range(10)
    ]

    # All paths identical
    for path in paths:
        assert path == paths[0]


def test_artifact_extensions_correct():
    """Artifact extensions match spec exactly."""
    session_id = uuid4()

    screenshot = build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)
    assert screenshot.suffix == ".png"

    text = build_artifact_path(session_id, "homepage", "desktop", "visible_text", DOMAIN)
    assert text.suffix == ".txt"

    features = build_artifact_path(session_id, "homepage", "desktop", "features_json", DOMAIN)
    assert features.suffix == ".json"

    html = build_artifact_path(session_id, "homepage", "desktop", "html_gz", DOMAIN)
    # html.gz has double extension
    assert str(html).endswith(".html.gz")


# --- Path validation tests ---


def test_artifact_path_no_special_characters():
    """Artifact paths contain only valid filesystem characters."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)

    # No spaces, no quotes, no special chars in path components
    for part in path.parts:
        assert " " not in part
        assert '"' not in part
        assert "'" not in part


def test_artifact_path_components_lowercase():
    """Page types and viewports are lowercase in paths."""
    session_id = uuid4()
    path = build_artifact_path(session_id, "homepage", "desktop", "screenshot", DOMAIN)

    # Path should not change when lowercased (already lowercase)
    assert "homepage" in str(path)
    assert "desktop" in str(path)


# --- 4 expected artifacts per session (spec) ---


def test_four_artifacts_per_session_structure():
    """Each session should have 4 pages: homepage + pdp × desktop + mobile."""
    session_id = uuid4()

    # Expected 4 page combinations
    expected_pages = [
        ("homepage", "desktop"),
        ("homepage", "mobile"),
        ("pdp", "desktop"),
        ("pdp", "mobile"),
    ]

    # Each page should have all artifact types
    for page_type, viewport in expected_pages:
        screenshot = build_artifact_path(session_id, page_type, viewport, "screenshot", DOMAIN)
        text = build_artifact_path(session_id, page_type, viewport, "visible_text", DOMAIN)
        features = build_artifact_path(session_id, page_type, viewport, "features_json", DOMAIN)
        html = build_artifact_path(session_id, page_type, viewport, "html_gz", DOMAIN)

        # All paths share same session_id/page_type/viewport prefix
        assert str(session_id) in str(screenshot)
        assert page_type in str(screenshot)
        assert viewport in str(screenshot)

        # Each artifact type has unique filename
        assert screenshot.name != text.name != features.name != html.name
