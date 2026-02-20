# Developer Guide

## Adding a New Audit Question

### 1. Create Question via API

```bash
curl -X POST http://localhost:8000/audits/questions \
  -H "Content-Type: application/json" \
  -d '{
    "category": "Awareness",
    "question": "Is there a clear return policy link?",
    "ai_criteria": "Look for return policy link in footer or navigation. Check both desktop and mobile versions.",
    "tier": 1,
    "severity": 5,
    "bar_chart_category": "Trust & Policies",
    "exact_fix": "Add a clear \"Returns\" link in the footer",
    "page_type": "homepage"
  }'
```

### 2. Question Fields

- **category**: `Awareness` | `Consideration` | `Conversion`
- **question**: Question text (what to check)
- **ai_criteria**: Instructions for AI evaluator
- **tier**: Priority tier (1-3)
  - Tier 1: Critical, must pass
  - Tier 2: Important, included if Tier 1 passes
  - Tier 3: Nice to have, included if Tier 1+2 pass
- **severity**: Importance (1-5, 5 = highest)
- **bar_chart_category**: Category for bar chart grouping
- **exact_fix**: Actionable fix text (shown in report)
- **page_type**: `homepage` | `pdp` | `cart` | `checkout`

### 3. Question Evaluation

Questions are evaluated automatically during audit:
- Loaded by `page_type` from `audit_questions` table
- Evaluated using OpenAI Responses API
- Results stored in `audit_results` table
- Included in report based on tier logic

## Adding a New Page Type

### 1. Update Database Schema

Add new page type to enum in migration:
```python
# migrations/versions/XXXX_add_new_page_type.py
op.execute("ALTER TYPE page_type_enum ADD VALUE 'new_page_type'")
```

### 2. Update Crawler

Add crawl function in `worker/crawl_runner.py`:
```python
async def crawl_new_page_type_async(...):
    # Similar to crawl_homepage_async
    pass
```

### 3. Update Orchestrator

Add to `worker/orchestrator.py`:
```python
# In run_audit_session()
if new_page_type_needed:
    await crawl_new_page_type_async(...)
```

### 4. Update Schemas

Update `api/schemas.py`:
```python
page_type: Literal["homepage", "pdp", "cart", "checkout", "new_page_type"]
```

## Adding a New Score Metric

### 1. Add Score Field to Session

Create migration:
```python
# migrations/versions/XXXX_add_new_score.py
op.add_column('audit_sessions', sa.Column('new_score', sa.Float()))
```

### 2. Compute Score

Add function in `worker/orchestrator.py`:
```python
def compute_new_score(session_uuid: UUID, repository: AuditRepository) -> float:
    # Compute score logic
    return score
```

### 3. Store Score

Update `run_audit_session()`:
```python
new_score = compute_new_score(session_uuid, repository)
repository.update_session_new_score(session_uuid, new_score)
```

### 4. Update Overall Score

Update `compute_overall_audit_score()` to include new score.

### 5. Update Schema

Add field to `AuditSessionResponse` in `api/schemas.py`.

## Customizing Report Generation

### 1. Modify Tier Logic

Edit `worker/report_generator.py`:
```python
# In generate_audit_report()
# Modify tier logic as needed
```

### 2. Add Custom Category Score

Add function in `worker/report_generator.py`:
```python
def _calculate_custom_score(questions: list[dict]) -> float:
    # Custom scoring logic
    return score
```

### 3. Customize Stage Summaries

Edit `worker/stage_summary_generator.py`:
- Modify prompt in `_build_summary_prompt()`
- Adjust summary length/tone
- Change evidence selection logic

### 4. Customize Storefront Report Card

Edit `worker/storefront_report_card.py`:
- Modify stage description prompt
- Adjust final thoughts format
- Change scoring thresholds

## Adding a New Artifact Type

### 1. Update Database Schema

Add to enum in migration:
```python
op.execute("ALTER TYPE artifact_type_enum ADD VALUE 'new_artifact_type'")
```

### 2. Capture Artifact

Add capture logic in `worker/crawl_runner.py`:
```python
# In crawl function
artifact_path = await capture_new_artifact(page, ...)
repository.create_artifact(
    session_id=session_id,
    page_id=page_id,
    type="new_artifact_type",
    storage_uri=artifact_path,
    size_bytes=size
)
```

### 3. Update Schema

Add to `ArtifactResponse` in `api/schemas.py`.

## Extending Evaluation Logic

### 1. Modify Evaluation Rules

Edit `audit_evaluator.py`:
- Update system instruction in `build_request()`
- Modify confidence gating rules
- Adjust PASS/FAIL/UNKNOWN criteria

### 2. Add Custom Evidence

Modify `build_request()` to include new evidence:
```python
# Add new evidence block
new_evidence = load_new_evidence(...)
content_items.append({
    "type": "input_text",
    "text": f"[NEW_EVIDENCE]\n{new_evidence}\n[/NEW_EVIDENCE]"
})
```

### 3. Custom Result Parsing

Modify `parse_response_json()` to handle custom result format.

## Adding Notifications

### 1. Telegram Notifications

Already implemented in `shared/telegram.py`:
```python
from shared.telegram import send_telegram_message

send_telegram_message(
    bot_token=config.telegram_bot_token,
    chat_id=config.telegram_chat_id,
    message="Alert message",
    parse_mode="HTML"
)
```

### 2. Add New Notification Channel

Create new module in `shared/`:
```python
# shared/slack.py or shared/email.py
def send_slack_message(...):
    # Implementation
    pass
```

## Testing

### Unit Tests

Location: `worker/tests/`

Run tests:
```bash
python -m pytest worker/tests/
```

### Integration Tests

Test full audit flow:
```bash
# Create session
curl -X POST http://localhost:8000/audits -d '{"url": "https://example.com"}'

# Wait for completion
# Check results
curl http://localhost:8000/audits/{session_id}/results
```

### Manual Testing

1. Start services (API + Worker)
2. Create audit session
3. Monitor logs
4. Verify artifacts created
5. Check results in database
6. Verify report generation

## Code Style

### Formatting

```bash
ruff format .
```

### Linting

```bash
ruff check .
```

### Type Hints

Use type hints for all function signatures:
```python
def function_name(param: str) -> dict:
    ...
```

### Logging

Use structured logging:
```python
from shared.logging import get_logger

logger = get_logger(__name__)

logger.info(
    "event_name",
    key1=value1,
    key2=value2
)
```

## Database Migrations

### Create Migration

```bash
alembic revision -m "description"
```

### Apply Migration

```bash
alembic upgrade head
```

### Rollback Migration

```bash
alembic downgrade -1
```

## Debugging

### Enable Debug Logging

```bash
export LOG_LEVEL=DEBUG
```

### Check Worker Logs

```bash
# Worker logs structured JSON
# Filter by session_id
grep "session_id.*{session_id}" worker.log
```

### Check Database

```sql
-- Check session
SELECT * FROM audit_sessions WHERE id = '{session_id}';

-- Check pages
SELECT * FROM audit_pages WHERE session_id = '{session_id}';

-- Check results
SELECT * FROM audit_results WHERE session_id LIKE '%{session_id}';

-- Check logs
SELECT * FROM crawl_logs WHERE session_id = '{session_id}' ORDER BY timestamp;
```

### Check Redis

```bash
redis-cli
> KEYS *
> GET throttle:domain:example.com
> LLEN rq:queue:audits
```

## Performance Optimization

### Batch Evaluation

Evaluation is already batched (max 30 questions per batch) in `audit_evaluator.py`.

### Parallel Crawling

Currently sequential. Can be parallelized:
```python
# In orchestrator.py
await asyncio.gather(
    crawl_homepage_desktop(...),
    crawl_homepage_mobile(...)
)
```

### Caching

Consider caching:
- Question lists (rarely change)
- Stage summaries (regenerate on result change)
- Category scores (recompute on result change)

## Security Considerations

### API Keys

- Never commit API keys
- Use environment variables
- Rotate keys regularly

### Database

- Use connection pooling
- Parameterized queries (SQLAlchemy handles this)
- Limit database user permissions

### File Storage

- Validate file paths (prevent directory traversal)
- Set appropriate file permissions
- Use checksums for integrity

## Common Patterns

### Repository Pattern

Data access through repository:
```python
from worker.repository import AuditRepository

repository = AuditRepository(session)
session_data = repository.get_session_by_id(session_id)
```

### Service Pattern

Business logic in service layer:
```python
from api.services.audit_service import AuditService

service = AuditService(repository)
response = service.create_audit_session(url=url, mode=mode)
```

### Dependency Injection

FastAPI handles DI:
```python
def get_audit_service(session: Session = Depends(get_db_session)):
    repository = AuditRepository(session)
    return AuditService(repository)
```

---

**End of Developer Guide**
