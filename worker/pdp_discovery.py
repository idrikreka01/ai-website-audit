"""
PDP discovery: validate candidates (2-of-4 rule), ensure PDP page records exist.

Logs: pdp_candidate_checked, pdp_selected, pdp_not_found. No behavior change.
"""

from __future__ import annotations

from uuid import UUID

from playwright.async_api import async_playwright

from shared.logging import bind_request_context, get_logger
from worker.constants import PDP_VIEWPORTS
from worker.crawl import (
    create_browser_context,
    extract_pdp_validation_signals,
    is_valid_pdp_page,
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
    bind_request_context(session_id=str(session_id), page_type="pdp")
    if not candidate_urls:
        logger.info("pdp_not_found", reason="no_candidates", session_id=str(session_id))
        return None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await create_browser_context(browser, "desktop")
        try:
            for pdp_url in candidate_urls:
                page = await context.new_page()
                try:
                    await page.goto(pdp_url, wait_until="domcontentloaded", timeout=15000)
                    await wait_for_page_ready(page, soft_timeout=8000)
                    signals = await extract_pdp_validation_signals(page)
                    repository.create_log(
                        session_id=session_id,
                        level="info",
                        event_type="navigation",
                        message="PDP candidate checked",
                        details={"url": pdp_url, "signals": signals},
                    )
                    logger.info(
                        "pdp_candidate_checked",
                        url=pdp_url,
                        session_id=str(session_id),
                        **signals,
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
