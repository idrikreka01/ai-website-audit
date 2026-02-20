# Quick Reference Guide

## Common Tasks

### Start an Audit
```bash
curl -X POST http://localhost:8000/audits \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example-shop.com", "mode": "standard"}'
```

### Check Session Status
```bash
curl http://localhost:8000/audits/{session_id}
```

### Get Report
```bash
curl http://localhost:8000/audits/{session_id}/report
```

### Get Results
```bash
curl http://localhost:8000/audits/{session_id}/results
```

### Get Artifacts
```bash
curl http://localhost:8000/audits/{session_id}/artifacts
```

## Score Interpretation

### Page Coverage Score (0-4)
- **4**: All pages crawled (homepage desktop/mobile + PDP desktop/mobile)
- **< 4**: Audit stops, marked partial

### AI Audit Score (0.0-1.0)
- **≥ 0.8**: High flag (green)
- **≥ 0.5**: Medium flag (yellow)
- **< 0.5**: Low flag (red)

### Functional Flow Score (0-3)
- **3**: All steps completed (add to cart + cart nav + checkout nav)
- **2**: Two steps completed
- **1**: One step completed
- **0**: No steps completed

### Overall Score (0-100)
- **≥ 70**: No manual review needed
- **< 70**: Manual review required (Telegram notification sent)

## Result Types

- **pass**: Criteria met on both desktop and mobile
- **fail**: Criteria NOT met AND confidence ≥ 8 AND clear evidence
- **unknown**: Evidence insufficient, unclear, or confidence < 8

## Tier Logic

- **Tier 1**: Must pass before Tier 2 included
- **Tier 2**: Included only if all Tier 1 pass
- **Tier 3**: Included only if all Tier 1 and Tier 2 pass

## File Locations

### Artifacts
```
artifacts/{domain}__{session_id}/
  ├── homepage/
  │   ├── desktop/
  │   │   ├── screenshot.png
  │   │   ├── visible_text.txt
  │   │   ├── features_json.json
  │   │   └── html_gz.html.gz
  │   └── mobile/
  │       └── ...
  ├── pdp/
  │   ├── desktop/
  │   └── mobile/
  └── session_logs.jsonl
```

### Code Structure
```
api/              # FastAPI service
worker/           # Playwright crawler
shared/           # Shared infrastructure
docs/             # Documentation
migrations/       # Alembic migrations
```

## Environment Variables (Required)

```bash
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://...
OPENAI_API_KEY=sk-...
```

## Environment Variables (Optional)

```bash
LOG_LEVEL=INFO
STORAGE_ROOT=./storage
ARTIFACTS_DIR=./artifacts
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Common Issues

### Session Stuck in "queued"
- Check Redis is running
- Check worker is running
- Check worker logs

### Session Status "partial"
- Page coverage < 4 (insufficient data)
- Some pages failed to crawl
- Check crawl logs for errors

### No AI Audit Score
- No audit results found
- Evaluation not run (page coverage < 4)
- Check evaluation logs

### Report Empty
- No results found
- Page coverage < 4
- Check session status
