#!/usr/bin/env python3
"""
Preview Report Renderer
=======================
Renders the Jinja2 report template with sample data and opens it in the browser.

Usage:
    python tools/preview_report.py                     # Uses default sample data
    python tools/preview_report.py --data my_data.json # Uses custom data file
    python tools/preview_report.py --no-open           # Render without opening browser

Output:
    templates/preview_output.html (rendered HTML file)
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DEFAULT_DATA_FILE = TEMPLATES_DIR / "sample_data.json"
OUTPUT_FILE = TEMPLATES_DIR / "preview_output.html"

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
        autoescape=False,  # HTML template manages its own escaping
        trim_blocks=True,
        lstrip_blocks=True,
    )

    template = env.get_template("report.html")
    rendered = template.render(**data)

    logger.info("Template rendered successfully (%d chars)", len(rendered))
    return rendered


def write_output(html: str, output_path: Path) -> None:
    """Write rendered HTML to disk."""
    output_path.write_text(html, encoding="utf-8")
    logger.info("Output written to %s", output_path)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Render the audit report template with sample data."
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
        default=str(OUTPUT_FILE),
        help="Path for rendered output (default: templates/preview_output.html)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open the result in a browser",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Load / Build data
    data_path = Path(args.data)
    if args.answers_session_root:
        data = build_report_data(data_path, Path(args.answers_session_root))
        logger.info("Built report data from answers at %s", args.answers_session_root)
    else:
        data = load_data(data_path)
    data = ensure_template_data(data)

    # Render
    html = render_template(data)

    # Write
    output_path = Path(args.output)
    write_output(html, output_path)

    # Open in browser
    if not args.no_open:
        url = output_path.as_uri()
        logger.info("Opening in browser: %s", url)
        webbrowser.open(url)
    else:
        print(f"Preview ready: {output_path}")


if __name__ == "__main__":
    main()
