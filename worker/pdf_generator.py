"""
PDF report generator using template_data_adapter and Playwright.

Generates PDF reports from JSON audit report data using the same template
system as tools/export_report_pdf.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    Environment = None
    FileSystemLoader = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from shared.config import get_config
from shared.logging import get_logger
from worker.report_generator import generate_audit_report
from worker.repository import AuditRepository

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DEFAULT_BASE_DATA = TEMPLATES_DIR / "sample_data.json"


def _load_json(path: Path) -> dict:
    """Load JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _adapt_report_data(report_data: dict) -> dict:
    """Adapt report JSON to template format using template_data_adapter logic."""
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from tools.template_data_adapter import ensure_template_data

        base_data = _load_json(DEFAULT_BASE_DATA) if DEFAULT_BASE_DATA.exists() else {}
        adapted = ensure_template_data(report_data, base_data=base_data)
        return adapted
    except ImportError as e:
        logger.warning(
            "template_data_adapter_not_available",
            message="Using report data as-is without adaptation",
            error=str(e),
        )
        return report_data


def _render_html(data: dict) -> str:
    """Render report.html template with data."""
    if Environment is None or FileSystemLoader is None:
        raise ImportError("jinja2 is required. Install with: pip install jinja2")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.html")
    rendered = template.render(**data)
    logger.info("template_rendered", chars=len(rendered))
    return rendered


def _html_to_pdf(html: str, output_path: Path) -> None:
    """Convert HTML to PDF using Playwright."""
    if sync_playwright is None:
        raise ImportError("playwright is required. Install with: pip install playwright")

    temp_html = TEMPLATES_DIR / "_temp_export.html"
    temp_html.write_text(html, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(temp_html.as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
            )
            browser.close()
            logger.info("pdf_generated", output_path=str(output_path))
    finally:
        if temp_html.exists():
            temp_html.unlink()


def generate_and_save_pdf_report(
    session_id: UUID,
    domain: str,
    repository: AuditRepository,
) -> Optional[str]:
    """
    Generate PDF report from audit session and save as artifact.

    Args:
        session_id: Audit session UUID
        domain: Domain name for artifact path
        repository: Audit repository instance

    Returns:
        Storage URI of saved PDF artifact, or None if generation failed
    """
    try:
        report_data = generate_audit_report(session_id, repository)

        if "error" in report_data:
            logger.error(
                "pdf_generation_failed_no_report_data",
                session_id=str(session_id),
                error=report_data.get("error"),
            )
            return None

        adapted_data = _adapt_report_data(report_data)
        html_content = _render_html(adapted_data)

        config = get_config()
        artifacts_root = Path(config.artifacts_dir)
        normalized_domain = (domain or "").strip().lower()
        if normalized_domain.startswith("www."):
            normalized_domain = normalized_domain[4:]
        normalized_domain = normalized_domain or "unknown-domain"
        root_name = f"{normalized_domain}__{session_id}"
        pdf_path = artifacts_root / root_name / "report.pdf"

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        _html_to_pdf(html_content, pdf_path)

        pdf_bytes = pdf_path.read_bytes()
        size = len(pdf_bytes)
        checksum = hashlib.md5(pdf_bytes).hexdigest()
        storage_uri = f"{root_name}/report.pdf"

        retention_until = datetime.now(timezone.utc) + timedelta(days=config.html_retention_days)

        repository.create_artifact(
            session_id=session_id,
            page_id=None,
            artifact_type="report_pdf",
            storage_uri=storage_uri,
            size_bytes=size,
            retention_until=retention_until,
            checksum=checksum,
        )

        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="artifact",
            message="PDF report generated and saved",
            details={
                "artifact_type": "report_pdf",
                "size_bytes": size,
                "checksum": checksum,
                "storage_uri": storage_uri,
            },
        )

        logger.info(
            "pdf_report_saved",
            session_id=str(session_id),
            storage_uri=storage_uri,
            size_bytes=size,
        )

        return storage_uri

    except Exception as e:
        logger.error(
            "pdf_report_generation_failed",
            session_id=str(session_id),
            error=str(e),
            error_type=type(e).__name__,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="artifact",
            message="PDF report generation failed",
            details={
                "artifact_type": "report_pdf",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        return None
