from __future__ import annotations

from uuid import UUID

from playwright.async_api import Page

from shared.config import get_config
from shared.logging import get_logger
from shared.telegram import send_telegram_message
from worker.checkout_flow import run_checkout_flow
from worker.repository import AuditRepository
from worker.simple_selector_discovery import discover_add_to_cart_xpaths

logger = get_logger(__name__)


async def simple_flow(
    page: Page,
    pdp_url: str,
    session_id: UUID,
    viewport: str,
    domain: str,
    repository: AuditRepository,
) -> dict:
    dynamic_add_to_cart_xpaths = await discover_add_to_cart_xpaths(page, top=10)

    logger.info(
        "simple_flow_starting",
        session_id=str(session_id),
        viewport=viewport,
        domain=domain,
        discovered_add_to_cart_count=len(dynamic_add_to_cart_xpaths),
    )
    repository.create_log(
        session_id=session_id,
        level="info",
        event_type="navigation",
        message="Simple flow selector discovery completed",
        details={
            "viewport": viewport,
            "domain": domain,
            "pdp_url": pdp_url,
            "discovered_add_to_cart_count": len(dynamic_add_to_cart_xpaths),
            "sample_selectors": dynamic_add_to_cart_xpaths[:3],
        },
    )
    config = get_config()
    if config.telegram_bot_token and config.telegram_chat_id:
        try:
            sample = dynamic_add_to_cart_xpaths[0] if dynamic_add_to_cart_xpaths else "NONE"
            msg = (
                "🧪 Simple flow: add-to-cart selectors\n"
                f"domain: {domain}\n"
                f"viewport: {viewport}\n"
                f"pdp_url: {pdp_url}\n"
                f"session_id: {session_id}\n"
                f"count: {len(dynamic_add_to_cart_xpaths)}\n"
                f"first_xpath: {sample}"
            )
            send_telegram_message(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
                message=msg,
            )
        except Exception:
            pass
    return await run_checkout_flow(
        page,
        pdp_url,
        {},
        session_id,
        viewport,
        domain,
        repository,
        simple_add_to_cart_xpaths=dynamic_add_to_cart_xpaths,
        simple_checkout_xpaths=[],
    )
