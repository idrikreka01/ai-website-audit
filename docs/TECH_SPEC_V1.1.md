# TECH SPEC V1.1 — Operational Addendum

**Version**: 1.1  
**Status**: Operational addendum + PDP validation tightening (v1.2)  
**References**: TECH_SPEC_V1.md, .cursorrules

---

All sections of **TECH_SPEC_V1.md** apply unchanged unless overridden below. This document consolidates key operational behavior for Redis lock/throttle, retention cleanup, and PDP validation. Implementation references: worker constants.py, locking.py, config (shared/config.py), cleanup.py, repository (get_expired_html_artifacts, mark_artifact_deleted), worker/crawl/pdp_validation.py.

---

## 0) Crawl policy version

- **crawl_policy_version**: `v1.2` (bumped for PDP validation tightening below).
- **v1.1**: PDP-not-found with homepage success → session status partial; Redis lock/throttle; retention cleanup.
- **v1.2**: PDP validation requires (price + title+image) plus at least one strong product signal (add-to-cart OR product schema) to reduce category/store-hub false positives.

---

## 1) Redis lock and throttle (operational)

### Key patterns
- **Lock key**: `lock:domain:{normalized_domain}`
  - Normalized domain: from URL, lowercase, strip protocol and optional `www` (e.g. `https://www.example.com/path` → `example.com`).
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

## 2) Retention cleanup (operational)

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
- **Behavior**: Runs one cleanup pass (loads .env, then executes cleanup and logs results). No scheduler in spec; see TECH_SPEC_V1.1.md for optional scheduling.

### Config (env)
- `RETENTION_CLEANUP_ENABLED` — used when cleanup is run by a scheduler (default false).
- `RETENTION_CLEANUP_BATCH_SIZE` — default 100.
- `RETENTION_CLEANUP_DRY_RUN` — default false.

---

## 3) PDP validation (tightened for v1.2)

- **Goal**: Reduce false positives on category/store-hub pages (e.g. Instacart) by requiring at least one strong product signal.
- **Rule**: A page is a valid PDP only if:
  1. **Base signals** (all required): price (currency + numeric or price element), product title + image (h1 or product-title class + at least one img).
  2. **Strong product signal** (at least one required): add-to-cart/buy button OR product schema.org JSON-LD.
- **Determinism**: Unchanged; signal extraction and evaluation remain deterministic. No other crawler behavior changes.
- **Implementation**: `worker/crawl/pdp_validation.py` — `evaluate_pdp_validation_signals` / `is_valid_pdp_page`.
