# AI Website Audit System — Complete Documentation

**Version**: 1.0  
**Last Updated**: 2026-02-20  
**Crawl Policy Version**: v1.24

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Data Flow & Lifecycle](#data-flow--lifecycle)
4. [API Reference](#api-reference)
5. [Worker Processes](#worker-processes)
6. [Database Schema](#database-schema)
7. [Report Generation](#report-generation)
8. [Scoring & Evaluation](#scoring--evaluation)
9. [Configuration](#configuration)
10. [Deployment](#deployment)

---

## System Overview

The AI Website Audit system is an automated e-commerce website auditing platform that:

- **Crawls** websites using Playwright (homepage, PDP, cart, checkout)
- **Captures** evidence artifacts (screenshots, HTML, visible text, features JSON)
- **Evaluates** websites against audit questions using OpenAI's Responses API
- **Generates** comprehensive reports with scores, summaries, and actionable findings
- **Scores** performance across three dimensions: Page Coverage, AI Audit, Functional Flow

### Key Features

- **Multi-viewport crawling**: Desktop and mobile versions of each page
- **AI-powered evaluation**: Uses OpenAI to evaluate questions against evidence
- **Tier-based reporting**: Questions organized by priority tiers (1-3)
- **Confidence gating**: FAIL results require high confidence (≥8) and clear evidence
- **UNKNOWN status**: Handles insufficient evidence gracefully
- **Manual review alerts**: Telegram notifications when scores < 70%
- **Comprehensive scoring**: Page coverage, AI audit, functional flow, and overall scores

---

## Architecture

### System Components

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ HTTP/REST
       ▼
┌─────────────────────────────────────────────────┐
│              FastAPI (API Layer)                │
│  - Request validation                           │
│  - Session management                           │
│  - Job enqueueing                               │
│  - Read-only endpoints                          │
└──────┬──────────────────────────────────────────┘
       │
       │ Redis Queue
       ▼
┌─────────────────────────────────────────────────┐
│          Worker (Playwright Crawler)            │
│  - Job consumption                              │
│  - Browser automation                           │
│  - Evidence capture                             │
│  - AI evaluation                                │
│  - Report generation                            │
└──────┬──────────────────────────────────────────┘
       │
       ├──────────────────┬──────────────────────┐
       ▼                  ▼                      ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ PostgreSQL  │  │ Redis        │  │ File Storage │
│ (Metadata)  │  │ (Queue/Locks)│  │ (Artifacts)  │
└─────────────┘  └──────────────┘  └──────────────┘
```

### Component Responsibilities

#### FastAPI (API Layer)
- **Location**: `api/`
- **Responsibilities**:
  - Accepts audit requests via REST API
  - Validates and normalizes URLs
  - Creates session records in PostgreSQL
  - Enqueues crawl jobs in Redis
  - Exposes read-only endpoints for:
    - Session status and metadata
    - Audit results
    - Artifacts
    - Questions
    - Reports (JSON)
  - Handles errors and returns user-safe messages

#### Worker (Playwright Crawler)
- **Location**: `worker/`
- **Responsibilities**:
  - Consumes jobs from Redis queue
  - Executes browser automation (Playwright)
  - Crawls pages (homepage, PDP, cart, checkout)
  - Captures evidence artifacts:
    - Screenshots (PNG)
    - Visible text (TXT)
    - Features JSON (structured data)
    - HTML (compressed)
  - Runs AI evaluation using OpenAI Responses API
  - Generates reports (JSON, optional PDF)
  - Computes scores (page coverage, AI audit, functional flow)
  - Sends Telegram notifications for manual review

#### PostgreSQL
- **Purpose**: Metadata and artifact references only (no binary blobs)
- **Stores**:
  - Session records (`audit_sessions`)
  - Page metadata (`audit_pages`)
  - Artifact references (`artifacts`)
  - Audit questions (`audit_questions`)
  - Audit results (`audit_results`)
  - Stage summaries (`audit_stage_summaries`)
  - Storefront report cards (`audit_storefront_report_cards`)
  - Crawl logs (`crawl_logs`)

#### Redis
- **Purpose**: Queueing, locking, throttling
- **Uses**:
  - **Queue**: RQ job queue for crawl workers
  - **Locks**: Per-domain locks to prevent concurrent crawls
  - **Throttles**: Domain-level rate limiting
  - **Job state**: Short-lived job metadata

#### File Storage
- **Purpose**: Binary artifact storage
- **Location**: Local filesystem or S3-compatible storage
- **Stores**:
  - Screenshots (`screenshot.png`)
  - Visible text (`visible_text.txt`)
  - Features JSON (`features_json.json`)
  - HTML (`html_gz.html.gz`)
  - Session logs (`session_logs.jsonl`)

### Shared Infrastructure

- **Location**: `shared/`
- **Components**:
  - `config.py`: Environment-based configuration
  - `logging.py`: Structured JSON logging (structlog)
  - `db.py`: Database connection and table metadata
  - `repository.py`: Data access layer (shared repository)
  - `telegram.py`: Telegram notification helpers

---

## Data Flow & Lifecycle

### Complete Audit Flow

```
1. API Request
   POST /audits
   ↓
2. Session Creation
   - Validate URL
   - Create session record (status='queued')
   - Enqueue job in Redis
   ↓
3. Worker Job Processing
   - Acquire domain lock
   - Apply throttle delay
   - Start session (status='running')
   ↓
4. Homepage Crawl
   - Desktop viewport
   - Mobile viewport
   - Capture artifacts
   ↓
5. PDP Discovery
   - Analyze homepage HTML
   - Find product links
   - Validate PDP (price + title + image)
   ↓
6. PDP Crawl (if found)
   - Desktop viewport
   - Mobile viewport
   - Capture artifacts
   ↓
7. Checkout Flow (optional)
   - Add to cart
   - Navigate to cart
   - Navigate to checkout
   - Capture load timings
   ↓
8. Page Coverage Check
   - Compute page_coverage_score (0-4)
   - If < 4: Stop, mark partial, notify
   ↓
9. AI Evaluation
   - Load questions by page_type
   - Build OpenAI request with evidence
   - Call Responses API (batched if needed)
   - Parse results (PASS/FAIL/UNKNOWN)
   - Store results in audit_results
   ↓
10. Score Computation
    - AI audit score (0.0-1.0) + flag
    - Overall score percentage
    - needs_manual_review flag
    ↓
11. Report Generation (on-demand)
    - Load results and questions
    - Apply tier logic
    - Generate stage summaries
    - Generate storefront report card
    - Calculate category scores
    ↓
12. Session Completion
    - Update status ('completed' | 'partial' | 'failed')
    - Release domain lock
    - Send Telegram notification (if needed)
```

### Session Status Transitions

```
queued → running → completed
              ↓
           partial
              ↓
           failed
```

- **queued**: Session created, job enqueued
- **running**: Worker processing
- **completed**: All pages crawled successfully, evaluation complete
- **partial**: Some pages failed or page coverage < 4
- **failed**: All pages failed or critical error

### Page Status

- **ok**: Page crawled successfully
- **failed**: Page crawl failed
- **pending**: Page not yet crawled

---

## API Reference

### Base URL
```
http://localhost:8000
```

### Endpoints

#### Create Audit Session
```http
POST /audits
Content-Type: application/json

{
  "url": "https://example-shop.com",
  "mode": "standard"
}
```

**Response** (201 Created):
```json
{
  "id": "uuid",
  "url": "https://example-shop.com",
  "status": "queued",
  "created_at": "2026-02-20T10:00:00Z"
}
```

#### Get Session
```http
GET /audits/{session_id}
```

**Response** (200 OK):
```json
{
  "id": "uuid",
  "url": "https://example-shop.com",
  "status": "completed",
  "page_coverage_score": 4,
  "ai_audit_score": 0.85,
  "ai_audit_flag": "high",
  "overall_score_percentage": 87.5,
  "needs_manual_review": false,
  "pages": [...]
}
```

#### Get Audit Results
```http
GET /audits/{session_id}/results
```

**Response** (200 OK):
```json
[
  {
    "result_id": 1,
    "question_id": 1,
    "session_id": "domain__uuid",
    "result": "pass",
    "reason": "Clear evidence found...",
    "confidence_score": 9
  }
]
```

#### Get Report
```http
GET /audits/{session_id}/report
```

**Response** (200 OK):
```json
{
  "session_id": "uuid",
  "url": "https://example-shop.com",
  "overall_score_percentage": 87.5,
  "overall_score": 87.5,
  "stage_scores": {
    "awareness": 90.0,
    "consideration": 85.0,
    "conversion": 88.0
  },
  "category_scores": [...],
  "questions": [...],
  "stage_summaries": [...],
  "storefront_report_card": {...},
  "actionable_findings": [...]
}
```

#### Get Questions
```http
GET /audits/questions?stage=Awareness&page_type=homepage
```

**Query Parameters**:
- `stage`: Filter by stage (Awareness, Consideration, Conversion)
- `page_type`: Filter by page type (homepage, pdp, cart, checkout)
- `category`: Filter by category

#### Get Question Results
```http
GET /audits/questions/{question_id}/results
```

#### Get Artifacts
```http
GET /audits/{session_id}/artifacts
```

**Response**:
```json
[
  {
    "id": "uuid",
    "type": "screenshot",
    "storage_uri": "artifacts/domain__uuid/homepage/desktop/screenshot.png",
    "size_bytes": 123456,
    "created_at": "2026-02-20T10:00:00Z"
  }
]
```

---

## Worker Processes

### Job Processing

**Entry Point**: `worker/jobs.py::process_audit_job()`

**Flow**:
1. Acquire domain lock (prevents concurrent crawls)
2. Apply throttle delay (rate limiting)
3. Open database session
4. Call `orchestrator.run_audit_session()`
5. Release lock in `finally` block

### Orchestrator

**Location**: `worker/orchestrator.py`

**Main Function**: `run_audit_session(url, session_uuid, repository)`

**Steps**:
1. **Homepage Crawl**: `crawl_homepage_async()` (desktop + mobile)
2. **PDP Discovery**: `run_pdp_discovery_and_validation()`
3. **PDP Crawl**: `crawl_pdp_async()` (if PDP found)
4. **Checkout Flow**: `run_checkout_flow()` (optional)
5. **Page Coverage**: `_compute_and_store_page_coverage()`
   - If < 4: Stop, mark partial, notify
6. **AI Evaluation**: `_run_audit_evaluation_for_page_types()`
7. **Score Computation**:
   - `compute_ai_audit_score()` → AI audit score + flag
   - `compute_overall_audit_score()` → Overall percentage
8. **Telegram Notification**: If `needs_manual_review` or page coverage < 4

### Crawl Runner

**Location**: `worker/crawl_runner.py`

**Functions**:
- `crawl_homepage_async()`: Crawls homepage (desktop + mobile)
- `crawl_pdp_async()`: Crawls PDP (desktop + mobile)
- `crawl_homepage_viewport()`: Single viewport crawl
- `crawl_pdp_viewport()`: Single viewport PDP crawl

**Crawl Process** (per viewport):
1. Launch browser context
2. Navigate to URL
3. Wait for page ready
4. Dismiss popups
5. Scroll page (progressive)
6. Capture artifacts:
   - Screenshot
   - Visible text
   - Features JSON
   - HTML (compressed)
7. Save artifacts to storage
8. Update page record in DB

### Checkout Flow

**Location**: `worker/checkout_flow.py`

**Function**: `run_checkout_flow()`

**Steps**:
1. Analyze PDP HTML for add-to-cart button
2. Click add-to-cart
3. Navigate to cart (capture load timings)
4. Navigate to checkout (capture load timings)
5. Return result dict with status for each step

**Scoring**: `compute_functional_flow_score()` returns 0-3:
- +1 for add_to_cart completed
- +1 for cart_navigation completed
- +1 for checkout_navigation completed

### AI Evaluation

**Location**: `audit_evaluator.py`

**Main Class**: `AuditEvaluator`

**Process**:
1. **Load Questions**: `get_questions_by_page_type(page_type)`
2. **Build Request**: `build_request(session_id, page_type, questions)`
   - Loads HTML chunks (desktop + mobile)
   - Loads visible text
   - Loads features JSON
   - Loads screenshots (optional)
   - Loads performance data
   - Builds system instruction with evaluation rules
3. **Call OpenAI**: `evaluate()` → Responses API
   - Batches questions (max 30 per batch)
   - Returns results dict
4. **Parse Results**: `parse_response_json()`
   - Normalizes PASS/FAIL/UNKNOWN
   - Validates confidence scores
5. **Save Results**: Store in `audit_results` table

**Evaluation Rules**:
- **PASS**: Criteria clearly met on both desktop and mobile
- **FAIL**: Criteria clearly NOT met AND confidence ≥ 8 AND clear evidence
- **UNKNOWN**: Evidence insufficient, unclear, conflicting, or confidence < 8

**Confidence Gating**:
- FAIL requires confidence ≥ 8
- If confidence < 8 → UNKNOWN (not FAIL)
- Prevents false negatives from insufficient evidence

---

## Database Schema

### Core Tables

#### `audit_sessions`
Session records with status, scores, and metadata.

**Key Fields**:
- `id` (UUID, PK)
- `url` (text, normalized)
- `status` (enum: queued, running, completed, failed, partial)
- `page_coverage_score` (int, 0-4)
- `ai_audit_score` (float, 0.0-1.0)
- `ai_audit_flag` (text: high, medium, low)
- `functional_flow_score` (int, 0-3)
- `overall_score_percentage` (float, 0-100)
- `needs_manual_review` (boolean)
- `pdp_url` (text, nullable)

#### `audit_pages`
Page-level metadata (homepage, PDP, cart, checkout).

**Key Fields**:
- `id` (UUID, PK)
- `session_id` (UUID, FK)
- `page_type` (enum: homepage, pdp, cart, checkout)
- `viewport` (enum: desktop, mobile)
- `status` (enum: ok, failed, pending)
- `load_timings` (jsonb)

#### `audit_questions`
Audit questions with tier, severity, and criteria.

**Key Fields**:
- `question_id` (int, PK)
- `category` (text: Awareness, Consideration, Conversion)
- `question` (text)
- `ai_criteria` (text)
- `tier` (int, 1-3)
- `severity` (int, 1-5)
- `bar_chart_category` (text)
- `exact_fix` (text)
- `page_type` (text)

#### `audit_results`
Evaluation results for each question.

**Key Fields**:
- `result_id` (int, PK)
- `question_id` (int, FK)
- `session_id` (text: `domain__uuid`)
- `result` (enum: pass, fail, unknown)
- `reason` (text)
- `confidence_score` (int, 1-10)

#### `audit_stage_summaries`
AI-generated summaries for each stage.

**Key Fields**:
- `id` (UUID, PK)
- `session_id` (UUID, FK)
- `stage` (text: Awareness, Consideration, Conversion)
- `summary` (text)
- `generated_at` (timestamptz)
- `model_version` (text)
- `token_usage` (jsonb)
- `cost_usd` (float)

#### `audit_storefront_report_cards`
Storefront report card with stage descriptions and final thoughts.

**Key Fields**:
- `id` (UUID, PK)
- `session_id` (UUID, FK)
- `stage_descriptions` (jsonb: {awareness, consideration, conversion})
- `final_thoughts` (text)
- `generated_at` (timestamptz)
- `model_version` (text)
- `token_usage` (jsonb)
- `cost_usd` (float)

#### `artifacts`
Artifact references (not binary data).

**Key Fields**:
- `id` (UUID, PK)
- `session_id` (UUID, FK)
- `page_id` (UUID, FK, nullable)
- `type` (enum: screenshot, visible_text, features_json, html_gz, session_logs_jsonl)
- `storage_uri` (text)
- `size_bytes` (bigint)
- `retention_until` (timestamptz, nullable)
- `deleted_at` (timestamptz, nullable)

#### `crawl_logs`
Structured crawl logs for debugging and auditing.

**Key Fields**:
- `id` (bigint, PK)
- `session_id` (UUID, FK)
- `level` (enum: info, warn, error)
- `event_type` (enum: navigation, popup, retry, timeout, error, artifact)
- `message` (text)
- `details` (jsonb)
- `timestamp` (timestamptz)

### Relationships

```
audit_sessions (1) ──< (many) audit_pages
audit_sessions (1) ──< (many) audit_results
audit_sessions (1) ──< (many) artifacts
audit_sessions (1) ──< (many) crawl_logs
audit_sessions (1) ──< (1) audit_stage_summaries (per stage)
audit_sessions (1) ──< (1) audit_storefront_report_cards

audit_questions (1) ──< (many) audit_results
audit_pages (1) ──< (many) artifacts
```

---

## Report Generation

### Report Generator

**Location**: `worker/report_generator.py`

**Main Function**: `generate_audit_report(session_id, repository)`

### Tier Logic

Questions are organized into tiers (1-3):

- **Tier 1**: Must pass before Tier 2 questions are included
- **Tier 2**: Included only if all Tier 1 pass
- **Tier 3**: Included only if all Tier 1 and Tier 2 pass

**Logic**:
```python
tier1_passed = all(r["result"] == "pass" for r in tier1_results)
tier2_passed = all(r["result"] == "pass" for r in tier2_results) if tier1_passed else False

if not tier1_passed:
    report_questions = tier1_results  # Only Tier 1
elif not tier2_passed:
    report_questions = tier1_results + tier2_results  # Tier 1 + 2
else:
    report_questions = tier1_results + tier2_results + tier3_results  # All tiers
```

### Severity Ordering

Questions are ordered by severity (highest to lowest):
- Severity 5 = Highest priority
- Severity 1 = Lowest priority

### Category Scores

**Weighting Formula**:
- Tier weight: Tier 1 = 3, Tier 2 = 2, Tier 3 = 1
- Severity weight: 5 = 5, 4 = 4, 3 = 3, 2 = 2, 1 = 1
- Combined weight = `tier_weight × severity_weight`
- Question score = `weight × (1 if pass, 0 if fail)`
- Category score = `sum(weighted_scores) / sum(weights) × 100`

**UNKNOWN Handling**: UNKNOWN results are excluded from weighted score calculation but included in question list.

### Stage Summaries

**Location**: `worker/stage_summary_generator.py`

**Function**: `generate_stage_summaries(session_id, repository)`

**Process**:
1. Load questions and results for stage
2. Compute category severity sums
3. Select main theme (highest severity category)
4. Get eligible questions (Tier 1 + Tier 2 if Tier 1 passed)
5. Build evidence context (HTML quotes, screenshot descriptions)
6. Generate summary using OpenAI Chat API
7. Save to `audit_stage_summaries` table

**Summary Format**: 5 sentences:
1. Positive stage read (what's working)
2. Main theme and impact (biggest blocker)
3. Evidence pointer (where issue shows up)
4. Simple fix (actionable)
5. Outcome or test (expected improvement or A/B test)

### Storefront Report Card

**Location**: `worker/storefront_report_card.py`

**Function**: `generate_storefront_report_card(session_id, repository)`

**Process**:
1. Generate stage descriptions (1-2 sentences per stage)
2. Generate final thoughts (5 sentences, executive summary)
3. Save to `audit_storefront_report_cards` table

### Actionable Findings

Extracted from failed questions:
- High impact findings prioritized
- Includes `exact_fix` text from questions table
- Grouped by category and tier

### Report Structure

```json
{
  "session_id": "uuid",
  "url": "https://example.com",
  "overall_score_percentage": 87.5,
  "overall_score": 87.5,
  "stage_scores": {
    "awareness": 90.0,
    "consideration": 85.0,
    "conversion": 88.0
  },
  "category_scores": [
    {
      "category": "Navigation",
      "score": 95.0,
      "total_questions": 5,
      "total_weight": 45.0
    }
  ],
  "category_scores_by_stage": {
    "awareness": [...],
    "consideration": [...],
    "conversion": [...]
  },
  "tier1_passed": true,
  "tier2_passed": true,
  "tier3_included": true,
  "questions": [
    {
      "question_id": 1,
      "question": "Is there a clear return policy link?",
      "category": "Awareness",
      "bar_chart_category": "Trust & Policies",
      "tier": 1,
      "severity": 5,
      "exact_fix": "Add a clear 'Returns' link in the footer",
      "result": "pass",
      "reason": "Return policy link found in footer",
      "confidence_score": 9
    }
  ],
  "stage_summaries": [
    {
      "stage": "Awareness",
      "summary": "The homepage effectively communicates...",
      "generated_at": "2026-02-20T10:00:00Z",
      "model_version": "gpt-5.2"
    }
  ],
  "storefront_report_card": {
    "stage_descriptions": {
      "awareness": "Strong homepage messaging...",
      "consideration": "Product pages provide...",
      "conversion": "Checkout flow is streamlined..."
    },
    "final_thoughts": "Overall, the website demonstrates..."
  },
  "actionable_findings": [
    {
      "actionable_finding": "Add a clear 'Returns' link in the footer",
      "impact": "High",
      "category": "Trust & Policies",
      "tier": 1,
      "severity": 5,
      "question_id": 1
    }
  ],
  "needs_manual_review": false
}
```

---

## Scoring & Evaluation

### Page Coverage Score

**Range**: 0-4  
**Calculation**: Count of successfully crawled pages
- Homepage desktop: +1
- Homepage mobile: +1
- PDP desktop: +1
- PDP mobile: +1

**Threshold**: If < 4, audit stops (insufficient data)

### AI Audit Score

**Range**: 0.0-1.0  
**Flag**: high (≥0.8), medium (≥0.5), low (<0.5)

**Calculation**: Weighted average by confidence score
```python
for result in audit_results:
    if result == "unknown":
        continue  # Exclude UNKNOWN
    confidence = result.confidence_score
    passed = (result.result == "pass")
    total_weight += confidence
    if passed:
        weighted_pass += confidence

score = weighted_pass / total_weight
```

**UNKNOWN Handling**: UNKNOWN results are excluded from score calculation.

### Functional Flow Score

**Range**: 0-3  
**Calculation**: Count of completed checkout steps
- Add to cart completed: +1
- Cart navigation completed: +1
- Checkout navigation completed: +1

### Overall Score Percentage

**Range**: 0-100  
**Calculation**: Average of available flag percentages
```python
flag1_percentage = (page_coverage_score / 4.0) * 100.0
flag2_percentage = ai_audit_score * 100.0  # if available
flag3_percentage = (functional_flow_score / 3.0) * 100.0

percentages = [flag1_percentage, flag3_percentage]
if flag2_percentage is not None:
    percentages.append(flag2_percentage)

overall_percentage = sum(percentages) / len(percentages)
```

**Manual Review**: If `overall_percentage < 70.0`, `needs_manual_review = True`

### Stage Scores

**Calculation**: Weighted average of category scores within stage
- Awareness: Homepage questions only
- Consideration: PDP questions only
- Conversion: Cart/checkout questions only

### Evaluation Process

1. **Question Loading**: Load questions by `page_type` from `audit_questions`
2. **Evidence Collection**:
   - HTML chunks (desktop + mobile, max 5 chunks each)
   - Visible text (desktop + mobile)
   - Features JSON (desktop + mobile)
   - Screenshots (desktop + mobile, optional)
   - Performance data (load timings)
3. **Request Building**: Construct OpenAI Responses API request
   - System instruction with evaluation rules
   - Evidence blocks as input_text/input_image
   - Questions as structured JSON schema
4. **API Call**: Call OpenAI Responses API
   - Batched if > 30 questions (max 30 per batch)
   - Returns structured JSON with results
5. **Result Parsing**: Parse and normalize results
   - Validate question_id, result, confidence_score
   - Normalize PASS/FAIL/UNKNOWN
   - Store in `audit_results` table

### Confidence Gating

**Rule**: FAIL requires confidence ≥ 8 AND clear evidence

**Rationale**: Prevents false negatives from insufficient evidence

**Flow**:
```
Evidence insufficient OR confidence < 8 → UNKNOWN
Evidence clear AND confidence ≥ 8 AND criteria NOT met → FAIL
Evidence clear AND criteria met → PASS
```

---

## Configuration

### Environment Variables

#### Database
- `DATABASE_URL`: PostgreSQL connection string
  - Format: `postgresql+psycopg://user:password@host:port/dbname`

#### Redis
- `REDIS_URL`: Redis connection string
  - Format: `redis://host:port/db`

#### Storage
- `STORAGE_ROOT`: Base path for artifact storage (local) or S3 URI
- `ARTIFACTS_DIR`: Directory for artifacts (default: `./artifacts`)

#### OpenAI
- `OPENAI_API_KEY`: OpenAI API key (required for evaluation)
- `OPENAI_PRICE_INPUT_PER_1M`: Input token price per 1M tokens (default: 2.50)
- `OPENAI_PRICE_OUTPUT_PER_1M`: Output token price per 1M tokens (default: 10.00)

#### HTML Analysis
- `HTML_ANALYSIS_MODE`: automatic | manual (default: automatic)
- `HTML_ANALYSIS_MODEL`: Model name (default: gpt-5.2)
- `HTML_ANALYSIS_SINGLE_REQUEST`: true | false (default: true)
- `HTML_ANALYSIS_MAX_HTML_CHARS`: Max HTML chars (default: 100000)

#### Logging
- `LOG_LEVEL`: DEBUG | INFO | WARNING | ERROR (default: INFO)
- `APP_ENV`: local | dev | staging | prod (default: local)

#### Telegram
- `TELEGRAM_BOT_TOKEN`: Bot token for notifications
- `TELEGRAM_CHAT_ID`: Chat ID for notifications

#### Worker
- `DISABLE_LOCKS`: true | false (default: false, for testing)
- `AUDIT_JOB_TIMEOUT_SECONDS`: Job timeout (default: 1200)

### Configuration Loading

**Location**: `shared/config.py`

**Function**: `get_config()`

**Behavior**:
- Loads from environment variables
- Provides sensible defaults
- Validates required variables
- Returns typed `Config` object

---

## Deployment

### Docker Compose

**File**: `docker-compose.yml`

**Services**:
- `postgres`: PostgreSQL 16
- `redis`: Redis 7
- `api`: FastAPI service
- `worker`: Worker service

**Volumes**:
- `postgres_data`: PostgreSQL data
- `redis_data`: Redis data
- `./storage:/app/storage`: Artifact storage
- `./artifacts:/app/artifacts`: Artifacts directory

### Local Development

#### Prerequisites
- Python 3.11+
- PostgreSQL 16+
- Redis 7+
- Playwright browsers

#### Setup

1. **Clone repository**
2. **Create virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. **Install dependencies**:
   ```bash
   pip install -r api/requirements.txt
   pip install -r worker/requirements.txt
   ```
4. **Install Playwright browsers**:
   ```bash
   playwright install
   ```
5. **Set environment variables** (`.env` file):
   ```bash
   DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ai_website_audit
   REDIS_URL=redis://localhost:6379/0
   OPENAI_API_KEY=sk-...
   ```
6. **Run migrations**:
   ```bash
   alembic upgrade head
   ```
7. **Start services**:
   ```bash
   # Terminal 1: API
   uvicorn api.main:app --reload
   
   # Terminal 2: Worker
   python -m worker.main
   ```

### Production Deployment

#### Requirements
- PostgreSQL (managed or self-hosted)
- Redis (managed or self-hosted)
- File storage (S3-compatible or local)
- Docker (optional)

#### Steps

1. **Database Setup**:
   - Create PostgreSQL database
   - Run migrations: `alembic upgrade head`

2. **Redis Setup**:
   - Deploy Redis instance
   - Configure connection string

3. **Storage Setup**:
   - Configure S3-compatible storage OR
   - Mount persistent volume for local storage

4. **API Deployment**:
   - Set environment variables
   - Deploy FastAPI service (Gunicorn + Uvicorn)
   - Configure reverse proxy (nginx)

5. **Worker Deployment**:
   - Set environment variables
   - Deploy worker service
   - Configure RQ workers (multiple for scaling)

6. **Monitoring**:
   - Log aggregation (structured JSON logs)
   - Health checks (`/health` endpoint)
   - Error tracking

### Health Checks

**API**: `GET /health`
- Returns 200 if healthy
- Checks database connectivity

**Worker**: Logs health status
- Checks Redis connectivity
- Checks database connectivity

---

## Additional Resources

- **Tech Spec**: `docs/TECH_SPEC_V1.1.md`
- **Database Schema**: `docs/db_schema.md`
- **Report Flow**: `docs/report_generation_flow.md`
- **UNKNOWN Status**: `IMPLEMENT_UNKNOWN_STATUS.md`

---

## Glossary

- **PDP**: Product Detail Page
- **Viewport**: Desktop or mobile browser viewport
- **Artifact**: Captured evidence (screenshot, HTML, text, JSON)
- **Tier**: Question priority level (1-3)
- **Severity**: Question importance level (1-5)
- **Stage**: Customer journey stage (Awareness, Consideration, Conversion)
- **Session**: Single audit run for a URL
- **Page Coverage**: Number of successfully crawled pages (0-4)
- **AI Audit Score**: Weighted score from evaluation results (0.0-1.0)
- **Functional Flow Score**: Checkout flow completion score (0-3)
- **Overall Score**: Combined performance percentage (0-100)
- **UNKNOWN**: Evaluation result when evidence is insufficient
- **Confidence Score**: Evaluator confidence in result (1-10)

---

**End of Documentation**
