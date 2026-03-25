from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from playwright.async_api import Page

from shared.config import get_config
from shared.logging import get_logger
from worker.checkout_flow import run_checkout_flow
from worker.html_analysis import analyze_product_html
from worker.repository import AuditRepository

logger = get_logger(__name__)


async def advance_flow(
    page: Page,
    pdp_url: str,
    html_content: str,
    page_id: int,
    session_id: UUID,
    viewport: str,
    domain: str,
    repository: AuditRepository,
) -> dict:
    analyze_product_html(
        html_content,
        session_id,
        page_id,
        "pdp",
        viewport,
        domain,
        repository,
    )

    config = get_config()
    artifacts_root = Path(config.artifacts_dir)
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain.startswith("www."):
        normalized_domain = normalized_domain[4:]
    normalized_domain = normalized_domain or "unknown-domain"
    root_name = f"{normalized_domain}__{session_id}"
    json_path = artifacts_root / root_name / "pdp" / "html_analysis.json"

    html_analysis_json: dict = {}
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            html_analysis_json = json.load(f)
        html_analysis_json["_file_path"] = str(json_path.absolute())

    logger.info(
        "advance_flow_starting",
        session_id=str(session_id),
        viewport=viewport,
        domain=domain,
    )
    return await run_checkout_flow(
        page,
        pdp_url,
        html_analysis_json,
        session_id,
        viewport,
        domain,
        repository,
    )
