#!/usr/bin/env python3
"""
PDF Report Generator
====================
Renders the Jinja2 report template with sample data, then converts
the HTML to a pixel-perfect PDF using Playwright (Chromium).

Each <section> in the HTML becomes exactly one page in the PDF.

Prerequisites:
    pip install jinja2 playwright
    playwright install chromium

Usage:
    python tools/generate_pdf.py                          # Default sample data
    python tools/generate_pdf.py --data my_data.json      # Custom data
    python tools/generate_pdf.py --output report.pdf      # Custom output path
    python tools/generate_pdf.py --preview                # Also open HTML in browser

Output:
    templates/report_output.pdf  (default)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import webbrowser
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
    print("Error: playwright is required. Install with:")
    print("  pip install playwright")
    print("  playwright install chromium")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DEFAULT_DATA_FILE = TEMPLATES_DIR / "sample_data.json"
DEFAULT_PDF_OUTPUT = TEMPLATES_DIR / "report_output.pdf"
HTML_INTERMEDIATE = TEMPLATES_DIR / "preview_output.html"

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


def render_template(data: dict) -> str:
    """Render report.html with the given data context."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template("report.html")
    rendered = template.render(**data)

    logger.info("Template rendered successfully (%d chars)", len(rendered))
    return rendered


def write_html(html: str, output_path: Path) -> None:
    """Write rendered HTML to disk."""
    output_path.write_text(html, encoding="utf-8")
    logger.info("HTML written to %s", output_path)


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    """Convert an HTML file to PDF using Playwright Chromium."""
    logger.info("Launching Chromium to generate PDF...")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Navigate to the local HTML file
        file_url = html_path.as_uri()
        page.goto(file_url, wait_until="networkidle")

        # Wait for fonts to load
        page.wait_for_timeout(1500)

        # Generate PDF with A4 sizing, no extra margins (CSS handles it)
        page.pdf(
            path=str(pdf_path),
            format="A4",
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            print_background=True,
            prefer_css_page_size=True,
        )

        browser.close()

    file_size_kb = pdf_path.stat().st_size / 1024
    logger.info("PDF generated: %s (%.1f KB)", pdf_path, file_size_kb)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate a PDF report from the audit template and sample data."
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
        default=str(DEFAULT_PDF_OUTPUT),
        help="Path for PDF output (default: templates/report_output.pdf)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Also open the intermediate HTML in a browser",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Step 1: Load / Build data
    data_path = Path(args.data)
    if args.answers_session_root:
        data = build_report_data(data_path, Path(args.answers_session_root))
        logger.info("Built report data from answers at %s", args.answers_session_root)
    else:
        data = load_data(data_path)
    data = ensure_template_data(data)

    # Step 2: Render HTML
    html = render_template(data)
    write_html(html, HTML_INTERMEDIATE)

    # Step 3: Convert HTML → PDF
    pdf_path = Path(args.output)
    html_to_pdf(HTML_INTERMEDIATE, pdf_path)

    print(f"\nPDF ready: {pdf_path}")

    # Optionally open preview
    if args.preview:
        webbrowser.open(HTML_INTERMEDIATE.as_uri())


if __name__ == "__main__":
    main()
