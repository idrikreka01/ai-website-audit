#!/usr/bin/env python3
"""
Manually trigger PDF generation for an existing audit session.

Usage:
    python3 tools/generate_pdf_manual.py <session_id>
    
Example:
    python3 tools/generate_pdf_manual.py b351cc10-894e-493b-aeec-20b419008f3e
"""

import sys
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from urllib.parse import urlparse

from shared.db import get_db_session
from shared.repository import AuditRepository
from worker.pdf_generator import generate_and_save_pdf_report


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/generate_pdf_manual.py <session_id>")
        print("\nExample:")
        print("  python3 tools/generate_pdf_manual.py b351cc10-894e-493b-aeec-20b419008f3e")
        sys.exit(1)

    try:
        session_id = UUID(sys.argv[1])
    except ValueError:
        print(f"Error: Invalid session ID format: {sys.argv[1]}")
        print("Session ID must be a valid UUID")
        sys.exit(1)

    db_session = next(get_db_session())
    repo = AuditRepository(db_session)

    session_data = repo.get_session_by_id(session_id)
    if not session_data:
        print(f"Error: Session {session_id} not found!")
        sys.exit(1)

    url = session_data.get("url", "")
    domain = urlparse(url).netloc or "unknown"
    status = session_data.get("status", "unknown")

    print(f"Session: {session_id}")
    print(f"URL: {url}")
    print(f"Domain: {domain}")
    print(f"Status: {status}")
    print("\nGenerating PDF report...")

    try:
        pdf_uri = generate_and_save_pdf_report(session_id, domain, repo)
        if pdf_uri:
            from shared.config import get_config

            config = get_config()
            pdf_path = Path(config.artifacts_dir) / pdf_uri
            print(f"\n✅ PDF generated successfully!")
            print(f"  Storage URI: {pdf_uri}")
            print(f"  Full path: {pdf_path}")
            if pdf_path.exists():
                size = pdf_path.stat().st_size
                print(f"  File size: {size:,} bytes ({size / 1024 / 1024:.2f} MB)")
            else:
                print("  ⚠️  Warning: File not found at expected path")
        else:
            print("\n❌ PDF generation failed. Check logs for details.")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error generating PDF: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
