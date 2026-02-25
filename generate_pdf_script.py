#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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
    print("Session not found!")
    sys.exit(1)

print(f"Session: {session_data.get('url')}")
domain = urlparse(session_data.get("url", "")).netloc or "unknown"
print(f"Domain: {domain}")
print("Generating PDF...")

pdf_uri = generate_and_save_pdf_report(session_id, domain, repo)
if pdf_uri:
    print(f"✅ PDF generated: {pdf_uri}")
    from shared.config import get_config

    config = get_config()
    pdf_path = Path(config.artifacts_dir) / pdf_uri
    print(f"Path: {pdf_path}")
    if pdf_path.exists():
        print(f"Size: {pdf_path.stat().st_size:,} bytes")
    else:
        print("⚠️  File not found at expected path")
else:
    print("❌ PDF generation failed")
