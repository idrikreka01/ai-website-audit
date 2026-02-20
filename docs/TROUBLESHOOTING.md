# Troubleshooting Guide

## Common Issues

### Session Stuck in "queued" Status

**Symptoms**: Session created but never starts processing

**Possible Causes**:
1. Worker not running
2. Redis connection issue
3. Domain lock held by another process
4. Job queue full

**Solutions**:
```bash
# Check worker is running
ps aux | grep "worker.main"

# Check Redis connection
redis-cli ping

# Check queue
redis-cli LLEN rq:queue:audits

# Check domain lock
redis-cli GET lock:domain:example.com

# Clear stuck lock (if safe)
redis-cli DEL lock:domain:example.com
```

### Session Status "partial"

**Symptoms**: Session completes but status is "partial" instead of "completed"

**Possible Causes**:
1. Page coverage < 4 (insufficient pages crawled)
2. Some pages failed to crawl
3. PDP not found

**Solutions**:
```bash
# Check page coverage score
curl http://localhost:8000/audits/{session_id} | jq .page_coverage_score

# Check page statuses
curl http://localhost:8000/audits/{session_id} | jq .pages[].status

# Check crawl logs
# Query database:
SELECT * FROM crawl_logs WHERE session_id = '{session_id}' AND level = 'error';
```

**Expected Behavior**: If page coverage < 4, audit stops early and marks as partial. This is by design to prevent unreliable evaluations.

### No AI Audit Score

**Symptoms**: `ai_audit_score` is `null` in session response

**Possible Causes**:
1. Page coverage < 4 (evaluation not run)
2. No audit results found
3. All results are UNKNOWN (excluded from score)

**Solutions**:
```bash
# Check page coverage
curl http://localhost:8000/audits/{session_id} | jq .page_coverage_score

# Check if results exist
curl http://localhost:8000/audits/{session_id}/results

# Check evaluation logs
# Look for "ai_audit_score_skipped" or "ai_audit_score_computed" in logs
```

### Evaluation Returns All UNKNOWN

**Symptoms**: All results have `result: "unknown"`

**Possible Causes**:
1. Insufficient evidence (HTML not captured)
2. Low confidence scores (< 8)
3. Evidence unclear or conflicting

**Solutions**:
```bash
# Check artifacts exist
curl http://localhost:8000/audits/{session_id}/artifacts

# Check HTML artifacts
ls artifacts/{domain}__{session_id}/*/desktop/html_gz.html.gz

# Check evaluation logs for confidence scores
# Query database:
SELECT result, confidence_score, reason FROM audit_results 
WHERE session_id LIKE '%{session_id}';
```

**Note**: UNKNOWN is expected when evidence is insufficient. This prevents false negatives.

### Report Empty or Missing Data

**Symptoms**: Report endpoint returns empty questions array or missing sections

**Possible Causes**:
1. No results found
2. Page coverage < 4 (report generation skipped)
3. Tier logic excludes questions

**Solutions**:
```bash
# Check results exist
curl http://localhost:8000/audits/{session_id}/results

# Check page coverage
curl http://localhost:8000/audits/{session_id} | jq .page_coverage_score

# Check tier logic
# If Tier 1 questions fail, only Tier 1 appears in report
```

### Worker Crashes or Hangs

**Symptoms**: Worker process dies or stops responding

**Possible Causes**:
1. Browser crash (Playwright)
2. Memory exhaustion
3. Database connection timeout
4. Job timeout exceeded

**Solutions**:
```bash
# Check worker logs
tail -f worker.log | grep ERROR

# Check system resources
top
free -h

# Check job timeout
# Default: 1200 seconds (20 minutes)
# Increase if needed: AUDIT_JOB_TIMEOUT_SECONDS=1800

# Restart worker
pkill -f "worker.main"
python -m worker.main
```

### Database Connection Errors

**Symptoms**: "Connection refused" or "Connection timeout"

**Possible Causes**:
1. PostgreSQL not running
2. Wrong connection string
3. Database doesn't exist
4. Connection pool exhausted

**Solutions**:
```bash
# Check PostgreSQL is running
pg_isready -h localhost -p 5432

# Test connection
psql -h localhost -U postgres -d ai_website_audit

# Check connection string format
echo $DATABASE_URL
# Should be: postgresql+psycopg://user:password@host:port/dbname

# Check connection pool settings
# In shared/db.py, adjust pool_size if needed
```

### Redis Connection Errors

**Symptoms**: "Connection refused" or "Connection timeout"

**Possible Causes**:
1. Redis not running
2. Wrong connection string
3. Redis max memory exceeded

**Solutions**:
```bash
# Check Redis is running
redis-cli ping

# Check connection string
echo $REDIS_URL
# Should be: redis://host:port/db

# Check Redis memory
redis-cli INFO memory

# Clear old keys (if safe)
redis-cli FLUSHDB
```

### Artifacts Not Created

**Symptoms**: No files in artifacts directory

**Possible Causes**:
1. Storage path incorrect
2. Permission issues
3. Disk full
4. Crawl failed before artifact capture

**Solutions**:
```bash
# Check storage path
echo $ARTIFACTS_DIR

# Check permissions
ls -la artifacts/

# Check disk space
df -h

# Check crawl logs for errors
# Query database:
SELECT * FROM crawl_logs 
WHERE session_id = '{session_id}' 
AND event_type = 'error';
```

### OpenAI API Errors

**Symptoms**: Evaluation fails with API error

**Possible Causes**:
1. Invalid API key
2. Rate limit exceeded
3. Insufficient credits
4. Model unavailable

**Solutions**:
```bash
# Check API key is set
echo $OPENAI_API_KEY | head -c 10

# Test API key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# Check rate limits in response headers
# Look for "x-ratelimit-remaining"

# Check account credits
# Visit OpenAI dashboard
```

### Telegram Notifications Not Sent

**Symptoms**: No notification received when manual review needed

**Possible Causes**:
1. Telegram not configured
2. Invalid bot token
3. Invalid chat ID
4. Network issue

**Solutions**:
```bash
# Check configuration
echo $TELEGRAM_BOT_TOKEN | head -c 10
echo $TELEGRAM_CHAT_ID

# Test bot token
curl https://api.telegram.org/bot{TOKEN}/getMe

# Test sending message
curl https://api.telegram.org/bot{TOKEN}/sendMessage \
  -d "chat_id={CHAT_ID}&text=Test"
```

### Slow Performance

**Symptoms**: Audits take too long to complete

**Possible Causes**:
1. Large HTML pages
2. Many questions to evaluate
3. Network latency
4. Database slow queries

**Solutions**:
```bash
# Check evaluation batch size
# Default: 30 questions per batch
# Adjust in audit_evaluator.py if needed

# Check database indexes
# Ensure indexes exist on:
# - audit_sessions(status, created_at)
# - audit_pages(session_id, page_type, viewport)
# - audit_results(session_id, question_id)

# Profile database queries
# Enable query logging in PostgreSQL

# Check network latency
ping api.openai.com
```

### Migration Errors

**Symptoms**: Alembic migration fails

**Possible Causes**:
1. Database schema out of sync
2. Migration conflicts
3. Missing dependencies

**Solutions**:
```bash
# Check current revision
alembic current

# Check migration history
alembic history

# Check for conflicts
alembic check

# Rollback if needed
alembic downgrade -1

# Reapply
alembic upgrade head
```

## Debugging Tips

### Enable Debug Logging

```bash
export LOG_LEVEL=DEBUG
```

### Check Structured Logs

```bash
# Filter by session
cat worker.log | jq 'select(.session_id == "{session_id}")'

# Filter by event type
cat worker.log | jq 'select(.event_type == "error")'

# Filter by level
cat worker.log | jq 'select(.level == "error")'
```

### Database Queries

```sql
-- Check session status
SELECT id, status, page_coverage_score, ai_audit_score, overall_score_percentage
FROM audit_sessions
WHERE id = '{session_id}';

-- Check page statuses
SELECT page_type, viewport, status
FROM audit_pages
WHERE session_id = '{session_id}'
ORDER BY page_type, viewport;

-- Check results count
SELECT result, COUNT(*) as count
FROM audit_results
WHERE session_id LIKE '%{session_id}'
GROUP BY result;

-- Check recent errors
SELECT timestamp, level, event_type, message, details
FROM crawl_logs
WHERE session_id = '{session_id}'
AND level = 'error'
ORDER BY timestamp DESC
LIMIT 10;
```

### Redis Inspection

```bash
# List all keys
redis-cli KEYS "*"

# Check queue length
redis-cli LLEN rq:queue:audits

# Check domain locks
redis-cli KEYS "lock:domain:*"

# Check throttles
redis-cli KEYS "throttle:domain:*"

# Get job details
redis-cli GET rq:job:{job_id}
```

### Artifact Inspection

```bash
# List artifacts for session
ls -lh artifacts/{domain}__{session_id}/

# Check screenshot
file artifacts/{domain}__{session_id}/homepage/desktop/screenshot.png

# Check HTML size
du -h artifacts/{domain}__{session_id}/*/desktop/html_gz.html.gz

# View visible text
cat artifacts/{domain}__{session_id}/homepage/desktop/visible_text.txt | head -100
```

## Getting Help

### Check Logs First

Always check logs before asking for help:
1. Worker logs (`worker.log` or stdout)
2. API logs (`api.log` or stdout)
3. Database logs (PostgreSQL logs)
4. Crawl logs (in database: `crawl_logs` table)

### Gather Information

When reporting issues, include:
1. Session ID
2. Error messages from logs
3. Relevant log entries
4. Database queries showing state
5. Environment (local/prod, Python version, etc.)

### Common Log Events

**Session Lifecycle**:
- `audit_session_created`
- `audit_job_started`
- `audit_job_completed`
- `audit_job_failed`

**Crawling**:
- `homepage_crawl_started`
- `pdp_crawl_started`
- `page_artifacts_captured`

**Evaluation**:
- `audit_evaluation_started`
- `ai_audit_score_computed`
- `overall_score_computed`

**Errors**:
- `audit_job_failed`
- `page_crawl_failed`
- `evaluation_failed`
- `report_generation_failed`

---

**End of Troubleshooting Guide**
