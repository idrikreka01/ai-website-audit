"""
Artifact storage helpers for local disk storage.

This module provides utilities for building artifact paths, writing artifacts,
and computing metadata (size, checksum) per the naming convention in TECH_SPEC.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from shared.config import get_config
from shared.logging import get_logger

logger = get_logger(__name__)

ArtifactType = Literal["screenshot", "visible_text", "features_json", "html_gz"]
PageType = Literal["homepage", "pdp"]
Viewport = Literal["desktop", "mobile"]


def build_artifact_path(
    session_id: UUID,
    page_type: PageType,
    viewport: Viewport,
    artifact_type: ArtifactType,
    domain: str,
) -> Path:
    """
    Build the artifact file path per naming convention.

    Convention: {session_id}__{domain}/{page_type}/{viewport}/{artifact_type}.{ext}

    Artifacts at the same path are overwritten deterministically (no skip-if-exists).
    Returns a Path object (does not create the file or directory).
    """
    config = get_config()
    artifacts_root = Path(config.artifacts_dir)

    # Determine file extension
    ext_map = {
        "screenshot": "png",
        "visible_text": "txt",
        "features_json": "json",
        "html_gz": "html.gz",
    }
    ext = ext_map[artifact_type]

    normalized_domain = _normalize_domain(domain)
    root_name = f"{session_id}__{normalized_domain}"
    path = artifacts_root / root_name / page_type / viewport / f"{artifact_type}.{ext}"

    return path


def _normalize_domain(domain: str) -> str:
    """Normalize domain: lowercase and strip leading www."""
    value = (domain or "").strip().lower()
    if value.startswith("www."):
        value = value[4:]
    return value or "unknown-domain"


def ensure_artifact_dir(path: Path) -> None:
    """Ensure the directory for an artifact path exists."""
    path.parent.mkdir(parents=True, exist_ok=True)


def write_screenshot(path: Path, image_bytes: bytes) -> tuple[int, str | None]:
    """
    Write screenshot bytes to disk.

    Returns (size_bytes, checksum). May raise OSError/IOError on write failure.
    """
    ensure_artifact_dir(path)
    path.write_bytes(image_bytes)
    size = len(image_bytes)
    checksum = hashlib.md5(image_bytes).hexdigest()
    return size, checksum


def write_text(path: Path, text: str) -> tuple[int, str | None]:
    """
    Write text content to disk (UTF-8).

    Returns (size_bytes, checksum). May raise OSError/IOError on write failure.
    """
    ensure_artifact_dir(path)
    text_bytes = text.encode("utf-8")
    path.write_bytes(text_bytes)
    size = len(text_bytes)
    checksum = hashlib.md5(text_bytes).hexdigest()
    return size, checksum


def write_json(path: Path, data: dict) -> tuple[int, str | None]:
    """
    Write JSON data to disk (UTF-8, pretty-printed).

    Returns (size_bytes, checksum). May raise OSError/IOError on write failure.
    """
    ensure_artifact_dir(path)
    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    path.write_bytes(json_bytes)
    size = len(json_bytes)
    checksum = hashlib.md5(json_bytes).hexdigest()
    return size, checksum


def write_html_gz(path: Path, html: str) -> tuple[int, str | None]:
    """
    Write HTML content as gzip-compressed file.

    Returns (size_bytes, checksum). May raise OSError/IOError on write failure.
    """
    ensure_artifact_dir(path)
    html_bytes = html.encode("utf-8")
    compressed = gzip.compress(html_bytes)
    path.write_bytes(compressed)
    size = len(compressed)
    checksum = hashlib.md5(compressed).hexdigest()
    return size, checksum


def get_storage_uri(path: Path) -> str:
    """
    Convert a local Path to a storage URI string.

    For local storage, this is just the relative path from artifacts root.
    """
    config = get_config()
    artifacts_root = Path(config.artifacts_dir)
    try:
        relative = path.relative_to(artifacts_root)
        return str(relative)
    except ValueError:
        # If path is not relative to artifacts root, return absolute path
        return str(path)
