# TECH SPEC V1.1 — AI-Powered Website Audit (Merged)

**Version**: 1.1  
**Status**: Full spec (V1) + operational addendum + PDP validation + popup policy (policy v1.24)

---

This document is the authoritative, merged specification. It includes all content from TECH_SPEC_V1.md plus the operational addendum and PDP validation tightening originally introduced in V1.1. If behavior changes, bump `crawl_policy_version`.

---

## 0) Crawl policy version

- **crawl_policy_version**: `v1.24` (Deterministic settle delays after popup/overlay; extraction retry on transient Playwright errors; see §5).
- **v1.1**: PDP-not-found with homepage success → session status partial; Redis lock/throttle; retention cleanup.
- **v1.2**: PDP validation requires price + title+image.
- **v1.3**: Navigation retry policy: attempts, backoff, timeouts, retryable classes, and bot-block detection with single mitigation retry (§5).
- **v1.4**: Retryable classes include HTTP 429 (rate-limit); logging reason `status_429`.
- **v1.5**: Artifact paths include a readable domain suffix for storage layout (§4).
- **v1.6**: Popup handling policy: categories, detection layers, safe-click order, max two passes per page, structured popup logging, failure handling (§5).
- **v1.7**: Pre-consent injection: vendor-level scripts + iframe application; logged as popup events (§5).
- **v1.8**: Pre-consent vendors expanded beyond OneTrust/Shopware (best-effort vendor DOM scripts).
- **v1.9**: Bot-block detection tightened to high-confidence indicators only (reduces false positives).
- **v1.10**: Bot-block detection tightened to highest-confidence indicators only (reduces false positives further).
- **v1.11**: PDP validation loosened to base signals only (price + title+image).
- **v1.12**: HTML is always stored (no conditional gating).
- **v1.13**: Increased minimum wait after load and added post-scroll settle delay.
- **v1.14**: Max reliability timings (3s minimum wait, 3s scroll waits, 3s post-scroll settle).
- **v1.17**: Progressive scroll sequence with incremental steps and bottom dwell.
- **v1.18**: Reduced waits to 2s (min wait, scroll wait, bottom dwell, post-scroll).
- **v1.19**: RQ job timeout set explicitly for audit jobs.
- **v1.20**: Artifact naming convention changed to domain-first (`{domain}__{session_id}/...`). New artifact type `session_logs_jsonl` for exported session logs. All session-scoped logs stored in `crawl_logs` and exported as session log artifact; session log retention is long-term (no cleanup).
- **v1.21**: Popup logging records only detected popup events (no selector-miss logs).
- **v1.22**: Popup logging records only dismiss events (success/failure); detected-ignored events are not logged.
- **v1.23**: Last-resort overlay hide fallback after safe-dismiss passes: blocked-page detection (large fixed/absolute overlay, scroll-lock or click-blocked); hide (no remove) in main doc + iframes, one pass; exclude structural nodes; single popup event `action=overlay_hide_fallback`.
- **v1.24**: Deterministic settle delays: after each popup dismiss click (configurable, e.g. 500 ms); after overlay hide fallback (configurable, e.g. 500 ms). Extraction retry policy: retry once (max 2 attempts total) on transient Playwright errors (execution context destroyed, target closed, navigation interrupted); retry flow: short wait_for_page_ready → optional popup pass → overlay fallback → retry extraction; log retries with `event_type=retry`, reason, attempt, page_type, viewport.

---

## 1) System Components & Responsibilities

- **FastAPI (API + Orchestration)**
  - Accepts audit requests, validates inputs, assigns session IDs.
  - Enqueues crawl jobs in Redis.
  - Exposes read-only endpoints for status, artifacts, and metadata.
  - Persists session metadata and state transitions in Postgres.

- **Worker (Playwright Crawler)**
  - Consumes jobs from Redis, executes browser crawl.
  - Produces evidence bundle (screenshots, visible text, features JSON, HTML).
  - Writes artifacts to storage (S3-compatible or local).
  - Writes session results, artifacts references, and logs to Postgres.

- **Redis**
  - **Queue**: job ingestion for crawl workers.
  - **Locks**: per-site or per-domain lock to prevent concurrent duplicate crawls.
  - **Rate limits**: domain-level throttling to reduce blocks and load.
  - **Job state**: short-lived job state (inflight, retry count).
  - **Job timeout**: `AUDIT_JOB_TIMEOUT_SECONDS` (default 1200s). Jobs exceeding this are killed by RQ.

- **PostgreSQL**
  - Stores session records, page-level metadata, artifact references, logs, and statuses.
  - Acts as the source of truth for session lifecycle.

- **Storage (S3-compatible or Local)**
  - Stores binary artifacts: screenshots, html.gz, visible text, feature JSON.
  - No business logic or evaluation logic stored here.

---

## 2) Crawl Session Contract (Conceptual Schema)

- **audit_session**
  - id (UUID)
  - url (normalized)
  - created_at (UTC)
  - status (queued | running | completed | failed | partial)
  - mode (standard | debug | evidence_pack)
  - retention_policy (standard | short | long)
  - attempts (integer)
  - final_url (after redirects)
  - crawl_policy_version (e.g., v1.24; PDP-not-found → partial; retry policy §5; popup policy §5; extraction retry §5)
  - error_summary (nullable)
  - config_snapshot (frozen crawl policy config for this run)
  - low_confidence (boolean)
  - pdp_url (nullable)

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
  - artifact_type (screenshot | visible_text | features_json | html_gz | session_logs_jsonl)
  - storage_uri
  - size_bytes
  - created_at
  - retention_until (nullable)
  - deleted_at (nullable; soft-delete marker set by retention cleanup)
  - checksum (optional)

- **logs** (crawl_logs)
  - session_id
  - level (info | warn | error)
  - event_type (navigation | popup | retry | timeout | error | artifact)
  - message
  - timestamp
  - details (structured key/value)
  - All session-scoped logs must be stored in crawl_logs and exported as a session log artifact (session_logs_jsonl).

---

## 3) Product Page Discovery Strategy

- **Primary path**
  - From homepage, collect candidate links:
    - URL patterns: /product, /products, /p/, /item
    - Presence of “add to cart” or price cues in link context
  - Prioritize links that appear in product grids or featured product sections.

- **Validation rules (v1.11)**
  - A page is a valid PDP only if:
    - **Base signals (all required)**: price (currency + numeric or price element), product title + image (h1 or product-title class + at least one img).
    - **Strong signals (tracked only)**: add-to-cart/buy button OR product schema.org JSON-LD.

- **Fallbacks**
  - If no candidates:
    - Inspect navigation for category pages → select first product found.
    - Scan internal links for “product” patterns across homepage DOM.
  - If still none:
    - Mark PDP as not found; session status becomes partial.

- **Determinism**
  - Always choose the first valid PDP by a stable ordering rule (DOM order).

---

## 4) Evidence Storage & Retention Rules

- **Always store**
  - Screenshots (desktop + mobile)
  - Visible text (cleaned DOM innerText)
  - Structured features JSON
  - HTML (html.gz)

- **Retention**
  - Always-stored artifacts: standard retention (long-lived)
  - HTML artifacts: short retention (default 14 days, configurable 7–30)
  - Session log artifacts (session_logs_jsonl): long-term retention; no cleanup (never deleted by retention job).

- **Retention cleanup**
  - Expired html_gz artifacts (retention_until < now) are deleted from storage and marked with deleted_at in the DB.
  - **Flow**: Query expired html_gz where deleted_at IS NULL → delete file from storage → set deleted_at = now.
  - **Dry-run**: When enabled, log candidates only; no file delete or DB update.
  - **Batch**: Configurable batch size per run (default 100).
  - **Manual CLI**: `python -m worker.cleanup` runs one cleanup pass; loads .env.
  - Session log artifacts are excluded from retention cleanup.

- **Naming convention** (v1.20: domain-first)
  - `{domain}__{session_id}/{path}`
  - `domain` is normalized: lowercase, strip leading `www.`.
  - Page-level artifacts: `{domain}__{session_id}/{page_type}/{viewport}/{artifact_type}.{ext}`
  - Session-level artifact: `{domain}__{session_id}/session_logs.jsonl`
  - Example: `example.com__session-uuid-123/homepage/desktop/screenshot.png`
  - Example: `example.com__session-uuid-123/session_logs.jsonl`

- **Session log export**
  - All session-scoped logs must be written to the `crawl_logs` table during the crawl.
  - At session end, the worker must export crawl_logs for that session to a single artifact of type `session_logs_jsonl` (e.g. one JSONL file per session, one log entry per line).
  - Storage path follows the domain-first naming above.

- **Compression**
  - HTML compressed as gzip (`html.gz`)
  - Visible text stored as plain UTF-8 text
  - Visible text optionally stored as both raw and cleaned variants

---

## 5) Playwright Reliability Policy (No Code)

- **Wait strategy**
  - Require: DOM stability + network idle window + minimum time after load.
  - Network idle window: no active network requests for 800ms.
  - DOM stability: no layout-shifting mutations for 1s.
  - Minimum wait after load: 2s.
  - Hard timeout cap per page to avoid infinite waits.

- **Scroll & lazy-load**
  - Progressive scroll sequence: incremental steps down the page, then bottom dwell, then return to top.
  - Wait after each step to allow lazy elements to load.
  - Bottom dwell: 2s to allow late lazy-loads.
  - Post-scroll settle delay: 2s before extraction and screenshots.

- **Popup Handling Policy** (v1.6)
  - **Popup categories**
    - Cookie consent / GDPR banners.
    - Newsletter / signup overlays.
    - Generic modal overlays (dismissible via button or backdrop).
  - **Detection layers**
    - **Layer 1**: Common selectors (data attributes, aria labels, class patterns for cookie/consent/newsletter).
    - **Layer 2**: Role/aria patterns (dialog, banner, region with dismiss CTA).
    - **Layer 3**: Visible overlay heuristics (fixed/sticky full-screen or centered modal with close/dismiss button).
  - **Safe-click rules**
    - Only click elements that are: visible, stable (in DOM and not animating), and match dismiss semantics (e.g. "accept", "agree", "close", "no thanks", "dismiss").
    - Prefer buttons/links with explicit dismiss intent; avoid submitting forms or navigating away.
    - One dismiss action per detected overlay per pass; deterministic order (e.g. by selector priority or DOM order).
  - **Settle delays** (v1.24)
    - **After popup dismiss click**: Wait a deterministic settle delay (e.g. 500 ms, configurable) after each successful or attempted dismiss click before continuing detection or extraction. Ensures DOM/overlays have time to update.
    - **After overlay hide fallback**: Wait a deterministic settle delay (e.g. 500 ms, configurable) after the overlay-hide fallback runs before proceeding to extraction. Ensures layout has settled.
  - **Two-pass flow**
    - **Pass 1**: After page load (or after navigation ready), run popup detection and safe dismiss in defined order. After each dismiss, apply the settle delay (see above).
    - **Pass 2**: If any dismiss occurred in pass 1, run detection once more (to catch secondary or delayed overlays). After each dismiss, apply the settle delay. Maximum two passes per page; no further popup passes after that.
  - **Logging requirements**
    - Log only dismiss events (no selector-miss logs; no detected-ignored logs).
    - For each dismiss event, log: `event_type: popup`; `selector` (or selector family); `action` (dismiss_click); `result` (success or failure); and page context (session_id, page_type, viewport, url or page identifier).
  - **Failure handling**
    - If a safe-click fails (element not found, not clickable, timeout): log and continue; do not fail the page. If overlays remain after both passes, log and continue with evidence capture. Page success is not conditional on popup dismissal.
  - **Last-resort overlay hide fallback** (v1.23)
    - **When**: Runs once per page, only after both safe-dismiss passes are complete. Applied only when the page is considered blocked.
    - **Blocked-page detection** (all must be satisfied to trigger fallback):
      - **Overlay heuristic**: At least one element is large fixed or absolute, has z-index ≥ 10, and covers a large portion of the viewport (>40% of viewport area).
      - **Blocking signal**: Either (a) document or body has scroll locked (e.g. overflow hidden, position fixed), or (b) a click at the viewport center is blocked or intercepted by an overlay (element at center is the overlay or its descendant).
    - **Fallback behavior**:
      - **Action**: Hide matching overlay elements (e.g. set `visibility: hidden` or equivalent); do not remove nodes from the DOM.
      - **Scope**: Apply in the main document and in all iframes (one pass per frame; do not recurse indefinitely).
      - **One pass only**: Run the hide step once per page; no second overlay-hide pass.
      - **Exclusions**: Do not hide structural nodes: `html`, `body`, `main`, `header`, `nav`, `footer`. Only hide elements that match the overlay heuristic above.
    - **Logging**: Emit a single popup event per page when the fallback runs: `event_type: popup`; `action: overlay_hide_fallback`; include summary details (e.g. count of elements hidden, frame count, whether scroll-lock or click-blocked was detected). If fallback does not run (page not considered blocked), do not log this event.
    - **After fallback**: Apply the deterministic settle delay (see Settle delays above) before proceeding to extraction.
  - **Pre-consent injection** (v1.7)
    - **Goal**: Suppress vendor-managed consent panels before UI renders.
    - **Vendors**: Apply known vendor scripts (initially OneTrust + Shopware-style off-canvas consent).
    - **Timing**:
      - **Before navigation**: add init scripts to the browser context so they execute on every new document.
      - **After navigation**: apply the same scripts in the main document and all iframes to handle iframe-based consent panels.
    - **Determinism**: No random delays; bounded scripts only.
    - **Logging**: Log a popup event with vendor list, frame count, and phase (init vs. post-nav). Failures are logged but non-fatal.

- **Navigation retry policy** (deterministic; v1.4)
  - **Attempts**: Max 3 navigation attempts per page load. Attempt 1 = initial goto; attempts 2–3 = retries after backoff.
  - **Backoff**: Exponential: 1s, then 2s, then 4s between attempts (configurable base/ceiling). Optional jitter 0–500 ms to avoid thundering herd.
  - **Timeouts**:
    - Per-attempt navigation timeout: 30 s (configurable). If exceeded, count as one failed attempt and apply backoff before next attempt.
    - Hard timeout per page: 90 s total (configurable). Total elapsed time includes goto attempts and all backoff between retries. If it exceeds this, stop retries and fail the page; session continues.
  - **Retryable classes**: Retry only on:
    - Navigation timeout (Playwright timeout on `goto` or equivalent).
    - Network failures: `net::ERR_*` (e.g. `net::ERR_CONNECTION_REFUSED`, `net::ERR_TIMED_OUT`, `net::ERR_NAME_NOT_RESOLVED`).
    - Blocked/restricted load: response status 403, 503, 429 (rate-limit), or challenge/captcha page (see bot-block below).
  - **Non-retryable**: Do not retry on 4xx (other than 403, 429), 5xx (other than 503), or client-side crashes. Log and fail the page.
  - **Bot-block detection and single mitigation retry**:
    - **Detection**: Treat as bot-block only for highest-confidence indicators after a successful navigation (e.g., "captcha", "verify you are human", "attention required", "cloudflare", "ddos protection"), or blocked HTTP status (403/503/429).
    - **Mitigation**: Exactly one additional attempt after bot-block detection: wait 2 s (configurable), then reload the same URL (same viewport, no UA change). No further retries for bot-block after this single mitigation.
    - **Logging**: Log `event_type: retry`, reason (e.g. `navigation_timeout`, `net_err`, `status_403_503`, `status_429`, `bot_block`), attempt number, and backoff applied.

- **Extraction retry policy** (v1.24)
  - **Purpose**: Recover from transient Playwright errors that can occur during or immediately after page ready (e.g. context/target closed, navigation interrupted).
  - **Triggers** (retry only on these; one retry per page, max 2 extraction attempts total):
    - Execution context destroyed (e.g. frame or context closed).
    - Target closed (e.g. page or browser context closed).
    - Navigation interrupted (e.g. new navigation or reload during extraction).
  - **Non-retryable**: Do not retry on permanent failures (e.g. selector timeout, assertion failure, invalid state). Log and fail the page.
  - **Retry flow** (when a trigger is hit on attempt 1):
    1. Short **wait_for_page_ready** (same readiness criteria as initial ready, bounded timeout).
    2. **Optional popup pass**: Run one popup detection + safe-dismiss pass (with settle delay after each dismiss).
    3. **Overlay fallback**: If blocked-page detection applies, run overlay hide fallback once, then apply settle delay.
    4. **Retry extraction**: Run extraction (screenshots, visible text, features, HTML) again. If this attempt fails (including with a retryable error), do not retry again; fail the page.
  - **Max attempts**: 2 (initial + 1 retry). No further retries after the first retry.
  - **Logging**: For each extraction retry, log `event_type: retry` with: `reason` (e.g. `execution_context_destroyed`, `target_closed`, `navigation_interrupted`), `attempt` (2 on retry), `page_type`, `viewport`, and session context. Include in crawl_logs and session log export.

- **Timeouts**
  - Soft timeouts for wait conditions (continue with warning).
  - Hard timeout to fail page and allow session to continue.

- **Anti-bot considerations**
  - Stable UA, viewport, timezone.
  - Rate limiting per domain via Redis.

---

## 6) PostgreSQL Data Model (Conceptual)

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

## 7) API Endpoints (Contract Only)

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

## 8) Excel Rubric Usage (Sprint 2+)

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

## 9) MVP Acceptance Criteria

- Works on 3 real e-commerce sites without manual intervention.
- Produces 4 screenshots per session (home + PDP × desktop + mobile).
- Visible text and features JSON stored for each page.
- HTML stored for every crawl (html.gz) with short retention.
- Runs are repeatable with the same outputs for identical inputs.
- Logs show navigation, wait conditions, dismissals, and retries.
- Implementation must meet senior-engineer quality: modular architecture, structured logging, typed contracts, and minimal tests for critical logic.

---

## 10) Open Decisions & Recommendations

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
  - Recommendation: missing H1, missing primary CTA, PDP missing price or title+image, text length below threshold, screenshot failed/blank.

---

## 11) Minimum Required features_json (Conceptual Schema)

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

## 12) Low-Confidence Flag (Deterministic Rules)

- Set low_confidence=true if any of the following are true:
  - H1 missing on the page.
  - Primary CTA not detected.
  - PDP missing price or title+image.
  - Visible text length below minimum threshold.
  - Screenshot missing, failed, or blank.

---

## 13) Visible Text Extraction Rules

- Extract from rendered DOM only.
- Exclude hidden nodes and aria-hidden content.
- Normalize whitespace (collapse multiples, trim).
- Store cleaned text; optionally also store raw text.

---

## 14) Policy Versioning & Comparability

- crawl_policy_version is mandatory for every session.
- config_snapshot is a frozen policy config used during the run.
- Sessions are comparable only within the same crawl_policy_version.
- Retention cleanup (deleted_at, cleanup job) is post-crawl maintenance and does not change crawl behavior; no crawl_policy_version bump required for retention cleanup.

---

## 15) Storage Rule Clarification

- Postgres stores metadata and artifact URIs only; no binary blobs.

---

## 16) Redis Lock and Throttle (Operational)

### Key patterns
- **Lock key**: `lock:domain:{normalized_domain}`
  - Normalized domain: from URL, lowercase, strip protocol and optional `www`.
- **Throttle key**: `throttle:domain:{normalized_domain}`
  - Value: Unix timestamp (milliseconds); used to enforce minimum delay between sessions for the same domain.

### TTLs and retries
- **Lock TTL**: 300 seconds (configurable via `DOMAIN_LOCK_TTL_SECONDS`).
- **Lock retries**: Max 3 attempts; exponential backoff with jitter (base 1s, 2s, 4s + 0–500 ms).
- **Lock timeout**: After max retries, job fails with `error_summary: "Domain lock timeout"`.
- **Throttle TTL**: 60 seconds (`DOMAIN_THROTTLE_TTL_SECONDS`).
- **Minimum delay**: 2000 ms between sessions per domain (`DOMAIN_MIN_DELAY_MS`).

### Disable flags
- **DISABLE_THROTTLE**: When true, skip throttle wait (e.g. testing).
- **DISABLE_LOCKS**: When true, skip lock acquire/release and throttle (e.g. testing).
- **Throttle bypass**: Also skipped for `mode=debug` sessions.

### Flow
- **Job start**: Throttle check → wait if needed → acquire domain lock (retry with backoff) → crawl.
- **Job end**: Release domain lock → update throttle key with current timestamp. Lock release in `finally` so it runs on success, failure, or partial.

### Logging events (structured; include session_id and domain)
- **Lock**: `lock.acquire.success`, `lock.acquire.retry`, `lock.acquire.timeout`, `lock.release.success`, `lock.release.stale`.
- **Throttle**: `throttle.wait`, `throttle.skip` (reason: debug_mode | testing).

---

## 17) Retention Cleanup (Operational)

### retention_until and deleted_at
- **retention_until**: Set at write time for html_gz artifacts only (now + configurable days, default 14). Other artifact types keep `retention_until` NULL (long-term).
- **deleted_at**: Nullable soft-delete marker on artifacts. Set by the retention cleanup job when an expired html_gz artifact is deleted from storage. NULL means not deleted.

### Cleanup flow
- **Query**: Expired html_gz where `retention_until < NOW()` and `deleted_at IS NULL`, ordered by `retention_until` ASC, limited by batch size.
- **Per artifact**: Delete file from storage (path = artifacts_dir + storage_uri); set `deleted_at = NOW()` in DB; log deletion. On failure, log error and continue batch.

### Dry-run and batch
- **Dry-run**: When `RETENTION_CLEANUP_DRY_RUN=true`, log candidates only; no file delete and no DB update.
- **Batch size**: Configurable via `RETENTION_CLEANUP_BATCH_SIZE` (default 100) per run.

### Manual CLI
- **Command**: `python -m worker.cleanup`
- **Behavior**: Runs one cleanup pass (loads .env, then executes cleanup and logs results). No scheduler in spec; optional scheduling can be added later if needed.

---

## 18) PDP Validation (Loosened for v1.11)

- **Goal**: Improve recall when add-to-cart or schema signals are missing.
- **Rule**: A page is a valid PDP only if:
  1. **Base signals (all required)**: price (currency + numeric or price element), product title + image (h1 or product-title class + at least one img).
  2. **Strong product signal (tracked only)**: add-to-cart/buy button OR product schema.org JSON-LD.
- **Determinism**: Unchanged; signal extraction and evaluation remain deterministic.

---

## Decision Checklist (for sign-off)

- Deterministic “page ready” rule approved
- PDP discovery rules approved
- Evidence bundle schema approved
- HTML retention window approved
- Concurrency and rate-limits approved
- MVP acceptance criteria confirmed
