**TECH SPEC V1 — AI-Powered Website Audit (Planning Only)**

---

**1) System Components & Responsibilities**

- **FastAPI (API + Orchestration)**
  - Accepts audit requests, validates inputs, assigns session IDs.
  - Enqueues crawl jobs in Redis.
  - Exposes read-only endpoints for status, artifacts, and metadata.
  - Persists session metadata and state transitions in Postgres.

- **Worker (Playwright Crawler)**
  - Consumes jobs from Redis, executes browser crawl.
  - Produces evidence bundle (screenshots, visible text, features JSON, optional HTML).
  - Writes artifacts to storage (S3-compatible or local).
  - Writes session results, artifacts references, and logs to Postgres.

- **Redis**
  - **Queue**: job ingestion for crawl workers.
  - **Locks**: per-site or per-domain lock to prevent concurrent duplicate crawls.
  - **Rate limits**: domain-level throttling to reduce blocks and load.
  - **Job state**: short-lived job state (inflight, retry count).

- **PostgreSQL**
  - Stores session records, page-level metadata, artifact references, logs, and statuses.
  - Acts as the source of truth for session lifecycle.

- **Storage (S3-compatible or Local)**
  - Stores binary artifacts: screenshots, html.gz, visible text, feature JSON.
  - No business logic or evaluation logic stored here.

---

**2) Crawl Session Contract (Conceptual Schema)**

- **audit_session**
  - id (UUID)
  - url (normalized)
  - created_at (UTC)
  - status (queued | running | completed | failed | partial)
  - mode (standard | debug | evidence_pack)
  - retention_policy (standard | short | long)
  - attempts (integer)
  - final_url (after redirects)
  - crawl_policy_version (e.g., v1.1; PDP-not-found → partial)
  - error_summary (nullable)
  - config_snapshot (frozen crawl policy config for this run)
  - low_confidence (boolean)

- **pages** (4 expected)
  - page_id
  - page_type (homepage | pdp)
  - viewport (desktop | mobile)
  - status (ok | failed | pending)
  - load_timings (timestamps + durations)
  - low_confidence_reasons (array)
  - evidence:
    - screenshot_ref
    - visible_text_ref
    - features_ref
    - html_ref (nullable)

- **artifacts**
  - artifact_id
  - artifact_type (screenshot | visible_text | features_json | html_gz)
  - storage_uri
  - size_bytes
  - created_at
  - retention_until (nullable)
  - deleted_at (nullable; soft-delete marker set by retention cleanup)
  - checksum (optional)

- **logs**
  - session_id
  - level (info | warn | error)
  - event_type (navigation | popup | retry | timeout | error | artifact)
  - message
  - timestamp
  - details (structured key/value)

---

**3) Product Page Discovery Strategy**

- **Primary path**
  - From homepage, collect candidate links:
    - URL patterns: /product, /products, /p/, /item
    - Presence of “add to cart” or price cues in link context
  - Prioritize links that appear in product grids or featured product sections.

- **Validation rules**
  - Must include at least two of:
    - Price pattern (currency + numeric)
    - Add-to-cart/buy button
    - Product schema.org JSON-LD
    - Product title + image cluster

- **Fallbacks**
  - If no candidates:
    - Inspect navigation for category pages → select first product found.
    - Scan internal links for “product” patterns across homepage DOM.
  - If still none:
    - Mark PDP as not found; session status becomes partial.

- **Determinism**
  - Always choose the first valid PDP by a stable ordering rule (DOM order).

---

**4) Evidence Storage & Retention Rules**

- **Always store**
  - Screenshots (desktop + mobile)
  - Visible text (cleaned DOM innerText)
  - Structured features JSON

- **Conditionally store html.gz**
  - Stored only if:
    - failed run
    - first-time crawl of site
    - low_confidence=true
    - explicit debug/evidence-pack mode

- **Retention**
  - Always-stored artifacts: standard retention (long-lived)
  - HTML artifacts: short retention (default 14 days, configurable 7–30)

- **Retention cleanup**
  - Expired html_gz artifacts (retention_until &lt; now) are deleted from storage and marked with deleted_at in the DB.
  - **Flow**: Query expired html_gz where deleted_at IS NULL → delete file from storage → set deleted_at = now.
  - **Dry-run**: When enabled, log candidates only; no file delete or DB update.
  - **Batch**: Configurable batch size per run (default 100).
  - **Manual CLI**: `python -m worker.cleanup` runs one cleanup pass; loads .env. No scheduling in spec; see TECH_SPEC_V1.1.md for scheduler options.

- **Naming convention**
  - `{session_id}/{page_type}/{viewport}/{artifact_type}.{ext}`
  - Example: `session123/homepage/desktop/screenshot.png`

- **Compression**
  - HTML compressed as gzip (`html.gz`)
  - Visible text stored as plain UTF-8 text
  - Visible text optionally stored as both raw and cleaned variants

---

**5) Playwright Reliability Policy (No Code)**

- **Wait strategy**
  - Require: DOM stability + network idle window + minimum time after load.
  - Network idle window: no active network requests for 800ms.
  - DOM stability: no layout-shifting mutations for 1s.
  - Hard timeout cap per page to avoid infinite waits.

- **Scroll & lazy-load**
  - Controlled scroll sequence: top → mid → bottom → top.
  - Short wait after each scroll to allow lazy elements to load.

- **Popups/cookies**
  - Detect and dismiss common overlays (cookie, newsletter).
  - Log all dismissals with selector and timestamp.

- **Retries**
  - Retry on navigation timeouts or blocked loads.
  - Exponential backoff with max retry cap.
  - Record retry reason in logs.

- **Timeouts**
  - Soft timeouts for wait conditions (continue with warning).
  - Hard timeout to fail page and allow session to continue.

- **Anti-bot considerations**
  - Stable UA, viewport, timezone.
  - Rate limiting per domain via Redis.

---

**6) PostgreSQL Data Model (Conceptual)**

- **audit_sessions**
  - id, url, status, created_at, final_url, mode, attempts, error_summary
  - crawl_policy_version, config_snapshot, low_confidence, pdp_url (nullable)

- **audit_pages**
  - id, session_id, page_type, viewport, status, load_timings
  - low_confidence_reasons

- **artifacts**
  - id, session_id, page_id, type, storage_uri, size_bytes, retention_until, deleted_at (nullable)

- **crawl_logs**
  - id, session_id, level, event_type, message, details, timestamp

- **Indexes**
  - audit_sessions(status, created_at)
  - audit_sessions(crawl_policy_version)
  - audit_pages(session_id, page_type, viewport)
  - artifacts(session_id, type)
  - crawl_logs(session_id, timestamp)

---

**7) API Endpoints (Contract Only)**

- **POST /audits**
  - Input: URL + mode (standard | debug)
  - Output: session ID + queued status

- **GET /audits/{id}**
  - Returns session metadata, status, timestamps, error summary

- **GET /audits/{id}/artifacts**
  - Returns artifact list with types and URIs

- **Status lifecycle**
  - queued → running → completed | failed | partial

- **Error behavior**
  - If PDP fails but homepage succeeds → partial (error_summary e.g. "PDP not found").
  - If both fail → failed with error summary

Note: For MVP, the API may use SQLAlchemy table reflection for DB access. Plan to
migrate to explicit ORM models before worker integration if domain complexity grows.

---

**8) Excel Rubric Usage (Sprint 2+)**

- **Primary/Secondary Payload**
  - Each question references specific artifact types only.
  - Evidence packaging will include only required payloads.

- **Complexity score**
  - Low complexity: binary answers if evidence is clear.
  - High complexity: allow “unclear” with rationale.
  - Complexity maps to confidence thresholds.

- **No prompt logic yet**
  - Only define evidence gating rules and packaging.

---

**9) MVP Acceptance Criteria**

- Works on 3 real e-commerce sites without manual intervention.
- Produces 4 screenshots per session (home + PDP × desktop + mobile).
- Visible text and features JSON stored for each page.
- HTML stored only under conditional rules.
- Runs are repeatable with the same outputs for identical inputs.
- Logs show navigation, wait conditions, dismissals, and retries.
- Implementation must meet senior-engineer quality: modular architecture, structured logging, typed contracts, and minimal tests for critical logic.

---

**10) Open Decisions & Recommendations**

- **Queue library**
  - Recommendation: RQ (Redis Queue) for MVP to reduce branching.

- **Concurrency**
  - Default global concurrency: 3 per worker.
  - Per-domain concurrency: 1 at a time.
  - Minimum delay per domain: 2 seconds between sessions.

- **Storage target**
  - Default: local disk for MVP; S3-compatible for production.

- **Retention**
  - Default: 14 days for html.gz; long-term for screenshots/text/features.

- **Determinism rules**
  - Recommendation: network idle + DOM stability window + minimum wait.

- **Low-confidence triggers**
  - Recommendation: missing H1, missing primary CTA, PDP missing price or add-to-cart, text length below threshold, screenshot failed/blank.

---

**Decision Checklist (for sign-off)**

- Deterministic “page ready” rule approved
- PDP discovery rules approved
- Evidence bundle schema approved
- HTML retention window approved
- Concurrency and rate-limits approved
- MVP acceptance criteria confirmed

---

**Minimum Required features_json (Conceptual Schema)**

- **meta**
  - title
  - meta_description
  - canonical_url

- **headings**
  - h1 (array)
  - h2 (array)

- **ctas**
  - text
  - href

- **navigation**
  - main_nav_links (text + href)
  - footer_links (text + href)

- **pdp_core** (PDP only)
  - price
  - currency
  - availability
  - add_to_cart_present (boolean)

- **schema_org**
  - product_detected (boolean)
  - product_fields (name, sku, brand, offers, aggregateRating)

- **review_signals**
  - review_count_present (boolean)
  - rating_value_present (boolean)

---

**Low-Confidence Flag (Deterministic Rules)**

- Set low_confidence=true if any of the following are true:
  - H1 missing on the page.
  - Primary CTA not detected.
  - PDP missing price or add-to-cart.
  - Visible text length below minimum threshold.
  - Screenshot missing, failed, or blank.

---

**Visible Text Extraction Rules**

- Extract from rendered DOM only.
- Exclude hidden nodes and aria-hidden content.
- Normalize whitespace (collapse multiples, trim).
- Store cleaned text; optionally also store raw text.

---

**Policy Versioning & Comparability**

- crawl_policy_version is mandatory for every session.
- config_snapshot is a frozen policy config used during the run.
- Sessions are comparable only within the same crawl_policy_version.
- Retention cleanup (deleted_at, cleanup job) is post-crawl maintenance and does not change crawl behavior; no crawl_policy_version bump required for retention cleanup.

---

**Storage Rule Clarification**

- Postgres stores metadata and artifact URIs only; no binary blobs.
