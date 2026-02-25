#!/usr/bin/env python3
"""Generate PDF report for a specific session ID."""

from uuid import UUID
from urllib.parse import urlparse

from shared.db import get_db_session
from shared.repository import AuditRepository
from worker.pdf_generator import generate_and_save_pdf_report

session_id = UUID("b351cc10-894e-493b-aeec-20b419008f3e")

db_session = next(get_db_session())
repo = AuditRepository(db_session)

session_data = repo.get_session_by_id(session_id)
if not session_data:
    print(f"Session {session_id} not found!")
    exit(1)

print(f"Session found:")
print(f"  URL: {session_data.get('url')}")
print(f"  Status: {session_data.get('status')}")

domain = urlparse(session_data.get("url", "")).netloc or "unknown"
print(f"  Domain: {domain}")
print(f"\nGenerating PDF report...")

pdf_uri = generate_and_save_pdf_report(session_id, domain, repo)

if pdf_uri:
    print(f"\n✅ PDF generated successfully!")
    print(f"  Storage URI: {pdf_uri}")
    from shared.config import get_config
    from pathlib import Path
    config = get_config()
    artifacts_root = Path(config.artifacts_dir)
    pdf_path = artifacts_root / pdf_uri
    print(f"  Full path: {pdf_path}")
    print(f"  File exists: {pdf_path.exists()}")
    if pdf_path.exists():
        print(f"  File size: {pdf_path.stat().st_size} bytes")
else:
    print(f"\n❌ PDF generation failed. Check logs for details.")
