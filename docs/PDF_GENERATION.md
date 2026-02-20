# PDF Generation Guide

## Purpose
This document explains how report PDFs are generated in this project, from raw audit artifacts/JSON to final A4 PDF output.

## High-Level Flow
1. Build or load report data.
2. Normalize data to the template contract.
3. Render `templates/report.html` with Jinja2.
4. Load rendered HTML in Playwright Chromium.
5. Export PDF with print backgrounds and zero margins.

## Core Files
- `templates/report.html`: Main Jinja template.
- `templates/report.css`: Visual + print layout rules.
- `tools/template_data_adapter.py`: Normalizes payloads (`reportF` style and others) into template shape.
- `tools/report_data_from_answers.py`: Builds report data from `answers.json` artifacts.
- `tools/preview_report.py`: Renders HTML preview only.
- `tools/generate_pdf.py`: Renders HTML and exports PDF.
- `tools/export_report_pdf.py`: Alternate PDF exporter (same architecture).
- `worker/pdf_report.py`: Worker-side/API PDF generation path.

## Data Inputs
PDF generation can start from:
- Template-ready JSON (for example `templates/purple.json`).
- `reportF`-style API payload JSON (adapted by `ensure_template_data`).
- Artifact session answers (`--answers-session-root`) via `build_report_data(...)`.

## Template Rendering Contract
All CLI tools pass data through:
- `ensure_template_data(...)` in `tools/template_data_adapter.py`

This ensures keys used in `templates/report.html` exist and are shaped correctly for Jinja rendering.

## HTML Preview (No PDF)
Use this to validate content/styling before export:

```bash
python3 tools/preview_report.py --data templates/purple.json --no-open
```

Output:
- `templates/preview_output.html` (or custom `--output`)

## PDF Export (Local)
Primary command:

```bash
python3 tools/generate_pdf.py --data templates/purple.json --output templates/report_output_from_purple.pdf
```

Alternative exporter:

```bash
python3 tools/export_report_pdf.py --data templates/purple.json --output templates/report_output_from_purple.pdf
```

### From artifact answers

```bash
python3 tools/generate_pdf.py \
  --data templates/sample_data.json \
  --answers-session-root artifacts/<session_root> \
  --output templates/report_output.pdf
```

## Worker/API Path
`worker/pdf_report.py` performs server-side PDF generation by:
- Fetching session/report context from repository.
- Rendering Jinja template from `worker/templates/base.html` (worker-specific template).
- Using Playwright to export A4 PDF.

This is separate from `templates/report.html` tooling and is used by backend flows.

## Print Layout Rules
`templates/report.css` contains `@media print` rules that enforce page behavior:
- Sections treated as A4 pages (`height: 297mm`, `page-break-after: always`).
- Last section has no trailing break.
- `print-color-adjust` enabled so dark backgrounds survive in PDF.

## Dependencies
Required for local generation:
- `jinja2`
- `playwright`
- Chromium browser for Playwright

Install:

```bash
pip install jinja2 playwright
playwright install chromium
```

## Common Issues
- `jinja2 is required`: install `jinja2`.
- `playwright is required`: install `playwright` and Chromium.
- Missing data keys in template: pass payload through `ensure_template_data`.
- Local browser-open issues from preview scripts do not block PDF export; check output file path.

## Recommended Validation Checklist
1. Render HTML preview first.
2. Verify section pagination with print CSS in browser print preview.
3. Export PDF.
4. Confirm:
   - A4 page count/order
   - no clipped critical content
   - backgrounds/colors preserved
   - links (where expected) are present in rendered HTML.
