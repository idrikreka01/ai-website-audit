## Database schema — metadata only (PostgreSQL)

This document summarizes the PostgreSQL schema for the AI Website Audit MVP.
It covers **metadata and artifact URIs only**; no binary blobs are stored in
Postgres, per the tech spec.

The schema is implemented via Alembic migrations in `migrations/`.


### Enums

- `audit_session_status_enum`: `queued`, `running`, `completed`, `failed`, `partial`
- `audit_mode_enum`: `standard`, `debug`, `evidence_pack`
- `retention_policy_enum`: `standard`, `short`, `long`
- `page_type_enum`: `homepage`, `pdp`
- `viewport_enum`: `desktop`, `mobile`
- `page_status_enum`: `ok`, `failed`, `pending`
- `artifact_type_enum`: `screenshot`, `visible_text`, `features_json`, `html_gz`
- `log_level_enum`: `info`, `warn`, `error`
- `event_type_enum`: `navigation`, `popup`, `retry`, `timeout`, `error`, `artifact`


### Table: `audit_sessions`

- `id` (`uuid`, PK)
- `url` (`text`, normalized URL, not null)
- `status` (`audit_session_status_enum`, not null)
- `created_at` (`timestamptz`, not null, default `now()`)
- `final_url` (`text`, nullable)
- `mode` (`audit_mode_enum`, not null)
- `retention_policy` (`retention_policy_enum`, not null)
- `attempts` (`integer`, not null, default `0`)
- `error_summary` (`text`, nullable)
- `crawl_policy_version` (`text`, not null)
- `config_snapshot` (`jsonb`, not null) — frozen crawl policy config for this run
- `low_confidence` (`boolean`, not null, default `false`)
- `pdp_url` (`text`, nullable) — selected PDP URL from discovery (Task 07)

Indexes:
- `ix_audit_sessions_status_created_at` on (`status`, `created_at`)
- `ix_audit_sessions_crawl_policy_version` on (`crawl_policy_version`)


### Table: `audit_pages`

- `id` (`uuid`, PK)
- `session_id` (`uuid`, FK → `audit_sessions.id` ON DELETE CASCADE)
- `page_type` (`page_type_enum`, not null)
- `viewport` (`viewport_enum`, not null)
- `status` (`page_status_enum`, not null)
- `load_timings` (`jsonb`, not null) — timestamps and durations for page load
- `low_confidence_reasons` (`jsonb`, not null) — array / structured reasons

Indexes:
- `ix_audit_pages_session_page_viewport` on (`session_id`, `page_type`, `viewport`)


### Table: `artifacts`

- `id` (`uuid`, PK)
- `session_id` (`uuid`, FK → `audit_sessions.id` ON DELETE CASCADE)
- `page_id` (`uuid`, FK → `audit_pages.id` ON DELETE CASCADE)
- `type` (`artifact_type_enum`, not null)
- `storage_uri` (`text`, not null) — URI or path to artifact in external storage
- `size_bytes` (`bigint`, not null)
- `created_at` (`timestamptz`, not null, default `now()`)
- `retention_until` (`timestamptz`, nullable)
- `deleted_at` (`timestamptz`, nullable) — soft delete marker for retention cleanup
- `checksum` (`text`, nullable)

Indexes:
- `ix_artifacts_session_type` on (`session_id`, `type`)


### Table: `crawl_logs`

- `id` (`bigint`, PK, auto-increment)
- `session_id` (`uuid`, FK → `audit_sessions.id` ON DELETE CASCADE)
- `level` (`log_level_enum`, not null)
- `event_type` (`event_type_enum`, not null)
- `message` (`text`, not null)
- `details` (`jsonb`, not null) — structured key/value metadata
- `timestamp` (`timestamptz`, not null, default `now()`)

Indexes:
- `ix_crawl_logs_session_timestamp` on (`session_id`, `timestamp`)
