#!/usr/bin/env python3
"""
CLI script for testing UniversalEcomNavigator.

Usage: python run_nav.py --url <site_url> [--no-headless]
"""

import argparse
import json
import sys
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from shared.db import get_db_session
from shared.logging import configure_logging
from worker.ecom_navigator import UniversalEcomNavigator
from worker.repository import AuditRepository


async def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Test UniversalEcomNavigator")
    parser.add_argument("--url", required=True, help="Homepage URL to navigate")
    parser.add_argument("--viewport", default="desktop", choices=["desktop", "mobile"])
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show browser window (Chrome). Use for local debugging.",
    )
    args = parser.parse_args()

    configure_logging()
    session_id = uuid4()

    with get_db_session() as db_session:
        repository = AuditRepository(db_session)
        session_data = repository.create_session(
            url=args.url,
            mode="standard",
            crawl_policy_version="1.0",
            config_snapshot={},
        )
        session_id = session_data["id"]

        navigator = UniversalEcomNavigator(
            base_url=args.url,
            session_id=session_id,
            repository=repository,
            viewport=args.viewport,
            headless=not args.no_headless,
        )

        result = await navigator.navigate()

        db_session.commit()

    print("\n" + "=" * 80)
    print("NAVIGATION RESULTS")
    print("=" * 80)
    print(f"\nProduct URL: {result.product_url or 'NOT FOUND'}")
    print(f"Product Status: {result.product_status}")
    print(f"\nCart URL: {result.cart_url or 'NOT FOUND'}")
    print(f"Cart Status: {result.cart_status}")
    print(f"\nCheckout URL: {result.checkout_url or 'NOT FOUND'}")
    print(f"Checkout Status: {result.checkout_status}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  - {error}")

    print("\n" + "=" * 80)
    print("JSON OUTPUT")
    print("=" * 80)
    print(
        json.dumps(
            {
                "product_url": result.product_url,
                "cart_url": result.cart_url,
                "checkout_url": result.checkout_url,
                "product_status": result.product_status,
                "cart_status": result.cart_status,
                "checkout_status": result.checkout_status,
                "errors": result.errors,
            },
            indent=2,
        )
    )

    if result.product_status != "found":
        sys.exit(1)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
