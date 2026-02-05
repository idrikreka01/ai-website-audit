"""
PDP discovery: validate candidates (2-of-4 rule), ensure PDP page records exist.

Logs: pdp_candidate_checked (with elapsed_ms, signals), pdp_selected, pdp_not_found.
No behavior change.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse
from uuid import UUID

from playwright.async_api import async_playwright

from shared.logging import bind_request_context, get_logger
from worker.constants import PDP_VIEWPORTS
from worker.crawl import (
    create_browser_context,
    extract_pdp_validation_signals,
    is_valid_pdp_page,
    navigate_with_retry,
    wait_for_page_ready,
)
from worker.repository import AuditRepository

logger = get_logger(__name__)


def ensure_pdp_page_records(session_id: UUID, repository: AuditRepository) -> None:
    """
    Ensure PDP page records exist for desktop and mobile; create pending if missing.
    """
    for page_type, viewport in PDP_VIEWPORTS:
        if not repository.page_exists(session_id, page_type, viewport):
            repository.create_page(
                session_id=session_id,
                page_type=page_type,
                viewport=viewport,
                status="pending",
            )


async def run_pdp_discovery_and_validation(
    candidate_urls: list[str],
    base_url: str,
    session_id: UUID,
    repository: AuditRepository,
) -> str | None:
    """
    Validate PDP candidates in order; return first URL that passes 2-of-4 rule, or None.

    Logs: pdp_candidate_checked, pdp_selected, pdp_not_found.
    """
    domain = urlparse(base_url).netloc or ""
    bind_request_context(
        session_id=str(session_id),
        page_type="pdp",
        viewport="desktop",
        domain=domain,
    )
    if not candidate_urls:
        logger.info("pdp_not_found", reason="no_candidates", session_id=str(session_id))
        return None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await create_browser_context(browser, "desktop")
        try:
            for pdp_url in candidate_urls:
                page = await context.new_page()
                try:
                    t0 = time.monotonic()
                    nav_result = await navigate_with_retry(
                        page,
                        pdp_url,
                        session_id=session_id,
                        repository=repository,
                        page_type="pdp",
                        viewport="desktop",
                        domain=domain,
                        nav_timeout_ms=15000,
                    )
                    if not nav_result.success:
                        logger.warning(
                            "navigation.failed",
                            url=pdp_url,
                            error_summary=nav_result.error_summary,
                            session_id=str(session_id),
                            page_type="pdp",
                            viewport="desktop",
                            domain=domain,
                        )
                        continue
                    await wait_for_page_ready(page, soft_timeout=8000)
                    signals = await extract_pdp_validation_signals(page)
                    elapsed_ms = (time.monotonic() - t0) * 1000
                    repository.create_log(
                        session_id=session_id,
                        level="info",
                        event_type="navigation",
                        message="PDP candidate checked",
                        details={
                            "url": pdp_url,
                            "signals": signals,
                            "elapsed_ms": round(elapsed_ms, 2),
                            "page_type": "pdp",
                            "viewport": "desktop",
                            "domain": domain,
                        },
                    )
                    logger.info(
                        "pdp_candidate_checked",
                        url=pdp_url,
                        elapsed_ms=round(elapsed_ms, 2),
                        has_price=signals.get("has_price"),
                        has_add_to_cart=signals.get("has_add_to_cart"),
                        has_product_schema=signals.get("has_product_schema"),
                        has_title_and_image=signals.get("has_title_and_image"),
                    )
                    if is_valid_pdp_page(signals):
                        logger.info(
                            "pdp_selected",
                            url=pdp_url,
                            session_id=str(session_id),
                        )
                        return pdp_url
                except Exception as e:
                    logger.warning(
                        "pdp_candidate_check_failed",
                        url=pdp_url,
                        error=str(e),
                        session_id=str(session_id),
                    )
                    continue
                finally:
                    await page.close()
        finally:
            await context.close()
            await browser.close()

    logger.info("pdp_not_found", reason="no_valid_candidate", session_id=str(session_id))
    return None
