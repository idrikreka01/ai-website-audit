#!/usr/bin/env python3
"""
Export Report to PDF
====================
Renders the Jinja2 report template with data, then uses Playwright (Chromium)
to convert the rendered HTML into a print-quality PDF.

Usage:
    python tools/export_report_pdf.py                          # Default sample data
    python tools/export_report_pdf.py --data my_data.json      # Custom data
    python tools/export_report_pdf.py --output report.pdf      # Custom output path
    python tools/export_report_pdf.py --no-open                # Don't open after export

Prerequisites:
    pip install jinja2 playwright
    playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

from report_data_from_answers import build_report_data
from template_data_adapter import ensure_template_data

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    print("Error: jinja2 is required. Install with: pip install jinja2")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright is required. Install with: pip install playwright")
    print("Then run: playwright install chromium")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DEFAULT_DATA_FILE = TEMPLATES_DIR / "sample_data.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "templates" / "report_output.pdf"

logger = logging.getLogger(__name__)


def load_data(data_path: Path) -> dict:
    """Load JSON data file and return as dict."""
    if not data_path.exists():
        logger.error("Data file not found: %s", data_path)
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info("Loaded data from %s (%d top-level keys)", data_path.name, len(data))
    return data


def render_html(data: dict) -> str:
    """Render report.html with the given data context."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.html")
    rendered = template.render(**data)
    logger.info("Template rendered (%d chars)", len(rendered))
    return rendered


def html_to_pdf(html: str, output_path: Path) -> None:
    """Use Playwright Chromium to convert HTML string to PDF."""
    # Write a temporary HTML file so Playwright can load it with proper
    # relative paths (for report.css, fonts, etc.)
    temp_html = TEMPLATES_DIR / "_temp_export.html"
    temp_html.write_text(html, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()

            # Navigate to the file (file:// protocol preserves relative CSS paths)
            page.goto(temp_html.as_uri(), wait_until="networkidle")

            # Generate PDF with print-friendly settings
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,  # Preserve dark backgrounds
                margin={
                    "top": "0mm",
                    "right": "0mm",
                    "bottom": "0mm",
                    "left": "0mm",
                },
            )

            browser.close()
            logger.info("PDF exported to %s", output_path)
    finally:
        # Clean up temp file
        if temp_html.exists():
            temp_html.unlink()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export the audit report as a PDF using Playwright."
    )
    parser.add_argument(
        "--data",
        type=str,
        default=str(DEFAULT_DATA_FILE),
        help="Path to JSON data file (default: templates/sample_data.json)",
    )
    parser.add_argument(
        "--answers-session-root",
        type=str,
        default=None,
        help="Artifact session root to build report data from answers.json files",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help="Output PDF path (default: templates/report_output.pdf)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open the PDF after export",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Load / Build data → Render → Export
    if args.answers_session_root:
        data = build_report_data(Path(args.data), Path(args.answers_session_root))
        logger.info("Built report data from answers at %s", args.answers_session_root)
    else:
        data = load_data(Path(args.data))
    data = ensure_template_data(data)
    html = render_html(data)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    html_to_pdf(html, output_path)

    # Open the PDF
    if not args.no_open:
        logger.info("Opening PDF...")
        if sys.platform == "darwin":
            subprocess.run(["open", str(output_path)], check=False)
        elif sys.platform == "linux":
            subprocess.run(["xdg-open", str(output_path)], check=False)
        elif sys.platform == "win32":
            subprocess.run(["start", str(output_path)], check=False, shell=True)
    else:
        print(f"PDF ready: {output_path}")


if __name__ == "__main__":
    main()
