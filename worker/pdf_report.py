"""
PDF report generator for audit results.

Generates a professional PDF report using HTML templates and converts to PDF.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from uuid import UUID

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from shared.logging import get_logger
from worker.report_generator import generate_audit_report
from worker.repository import AuditRepository

logger = get_logger(__name__)


def _create_chart_html(questions: list[dict]) -> str:
    """Create HTML bar chart grouped by bar_chart_category showing pass percentages."""
    category_stats = defaultdict(lambda: {"total": 0, "passed": 0})

    for q in questions:
        category = q.get("bar_chart_category", "Other")
        result = (q.get("result") or "").lower()
        category_stats[category]["total"] += 1
        if result == "pass":
            category_stats[category]["passed"] += 1

    categories = sorted(category_stats.keys())
    if not categories:
        return ""

    max_score = 100
    chart_html = '<div style="margin: 20px 0;">'

    for cat in categories:
        stats = category_stats[cat]
        if stats["total"] > 0:
            percentage = (stats["passed"] / stats["total"]) * 100
        else:
            percentage = 0

        bar_width = (percentage / max_score) * 100

        bar_outer = (
            "flex: 1; background: #ecf0f1; height: 25px; border-radius: 3px; "
            "margin-left: 10px; position: relative;"
        )
        bar_inner = (
            f"background: #3498db; height: 100%; width: {bar_width}%; border-radius: 3px; "
            "display: flex; align-items: center; justify-content: flex-end; padding-right: 5px;"
        )
        pct_style = "color:white;font-size:10px;font-weight:bold"
        chart_html += f"""
        <div style="margin-bottom: 15px;">
            <div style="display: flex; align-items: center; margin-bottom: 5px;">
                <div style="width: 200px; font-size: 11px; font-weight: bold;">{cat[:40]}</div>
                <div style="{bar_outer}">
                    <div style="{bar_inner}">
                        <span style="{pct_style}">{percentage:.0f}%</span>
                    </div>
                </div>
            </div>
        </div>
        """

    chart_html += "</div>"
    return chart_html


def generate_pdf_report(session_id: UUID, repository: AuditRepository, output_path: Path) -> Path:
    """
    Generate PDF report for audit session using HTML templates.

    Args:
        session_id: Session UUID
        repository: Audit repository
        output_path: Path where PDF will be saved

    Returns:
        Path to generated PDF file
    """
    if not JINJA2_AVAILABLE:
        raise ImportError("jinja2 is not installed. Install it with: pip install jinja2")

    if not PLAYWRIGHT_AVAILABLE:
        raise ImportError("playwright is not installed. Install it with: pip install playwright")

    report_data = generate_audit_report(session_id, repository)

    if "error" in report_data:
        logger.error(
            "pdf_report_generation_failed",
            session_id=str(session_id),
            error=report_data.get("error"),
        )
        raise ValueError(f"Cannot generate PDF: {report_data.get('error')}")

    questions = report_data.get("questions", [])
    failed_questions = [q for q in questions if (q.get("result") or "").lower() == "fail"]
    passed_questions = [q for q in questions if (q.get("result") or "").lower() == "pass"]
    unknown_questions = [q for q in questions if (q.get("result") or "").lower() == "unknown"]

    overall_score = report_data.get("overall_score_percentage", 0)
    score_class = "score-high" if overall_score >= 70 else "score-low"

    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "xml"])
    )

    template = env.get_template("base.html")

    chart_html = _create_chart_html(questions)

    html_content = template.render(
        url=report_data.get("url", "N/A"),
        overall_score=f"{overall_score:.1f}",
        score_class=score_class,
        chart_html=chart_html,
        failed_questions=failed_questions,
        passed_questions=passed_questions[:20],
        unknown_questions=unknown_questions,
        questions=questions,
    )

    html_path = output_path.with_suffix(".html")
    html_path.write_text(html_content, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html_content)
        page.pdf(
            path=str(output_path),
            format="Letter",
            margin={"top": "0.75in", "right": "0.75in", "bottom": "0.75in", "left": "0.75in"},
            print_background=True,
        )
        browser.close()

    html_path.unlink()

    logger.info(
        "pdf_report_generated",
        session_id=str(session_id),
        output_path=str(output_path),
        total_questions=len(questions),
        failed_count=len(failed_questions),
    )

    return output_path
