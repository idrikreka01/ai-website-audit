# ai-website-audit

## Overview

This repository contains the scaffolding for the **AI-powered website audit** project.
The goal of this stage is to provide a clean, two-service layout with shared
configuration and structured logging, without implementing any crawling logic,
endpoints, database models, or queueing behavior yet.

Services:
- `api/` — FastAPI-based orchestration service (request handling, session lifecycle).
- `worker/` — Playwright-based crawler worker (evidence capture, page processing).
- `shared/` — Cross-cutting infrastructure (config, logging) used by both services.


## Python tooling

This project uses a **pyproject-based** setup:

- Root `pyproject.toml` configures **black** and **ruff** for formatting and linting.
- `api/pyproject.toml` defines the API service runtime dependencies.
- `worker/pyproject.toml` defines the worker service runtime dependencies.

Recommended Python version: **3.11** or newer.


## Shared foundations

- `shared/config.py` — env-var-based configuration with sensible local defaults.
- `shared/logging.py` — structlog-based JSON logging with a shared context helper.

Both `api` and `worker` should import from `shared` rather than reconfiguring logging
or reimplementing config parsing.


## How to run locally — API

1. Create and activate a virtual environment (example):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install API dependencies:
   ```bash
   cd api
   pip install -r requirements.txt
   ```

3. Ensure the repository root is on `PYTHONPATH` (so `shared/` is importable). For
   simple local workflows, this can be done when launching processes, for example:
   ```bash
   export PYTHONPATH="$(cd .. && pwd)"
   ```

4. (Placeholder) Start the API server:
   ```bash
   # Actual FastAPI app entrypoint will be added in a later task.
   uvicorn api.main:app --reload  # Placeholder target
   ```


## How to run locally — Worker

1. Create and activate a virtual environment (you can reuse the same one as the API).

2. Install worker dependencies:
   ```bash
   cd worker
   pip install -r requirements.txt
   ```

3. Install Playwright browsers (one-time setup per environment):
   ```bash
   playwright install
   ```

4. Ensure the repository root is on `PYTHONPATH` so the worker can import from
   `shared/`:
   ```bash
   export PYTHONPATH="$(cd .. && pwd)"
   ```

5. (Placeholder) Start the worker process:
   ```bash
   # Actual worker entrypoint and queue consumption logic will be added later.
   python -m worker.main  # Placeholder target
   ```


## Environment configuration

Configuration is provided via environment variables and read by `shared.config`.
No secrets are committed to the repository.

Key variables:
- `APP_ENV` — deployment environment (`local` | `dev` | `staging` | `prod`), default: `local`.
- `LOG_LEVEL` — log level for both services (e.g., `INFO`, `DEBUG`), default: `INFO`.
- `DATABASE_URL` — Postgres connection string for metadata and artifacts references.
- `REDIS_URL` — Redis connection string for queueing, locks, and throttling.
- `STORAGE_ROOT` — base path or URI for artifact storage; default: `./storage`.
- `ARTIFACTS_DIR` — directory for storing crawl artifacts (screenshots, text, JSON, HTML); default: `./artifacts`.

For local development you may optionally use `python-dotenv` in each service
to load a `.env` file, but the contents of such files must not be committed.

Editable installs (`pip install -e .`) for the `api` and `worker` services will be
enabled once their Python package layouts are introduced in a later task.


## Manual smoke test (homepage crawl)

To verify the worker can crawl a homepage:

1. Ensure all services are running:
   - PostgreSQL (with migrations applied)
   - Redis
   - API server: `uvicorn api.main:app --reload`
   - Worker: `python -m worker.main`

2. Create an audit session:
   ```bash
   curl -X POST http://localhost:8000/audits \
     -H "Content-Type: application/json" \
     -d '{"url": "https://example.com", "mode": "standard"}'
   ```

3. Check the session status:
   ```bash
   curl http://localhost:8000/audits/{session_id}
   ```

4. Verify artifacts were created:
   - Check `./artifacts/{session_id}/homepage/desktop/` and `./artifacts/{session_id}/homepage/mobile/`
   - Should contain: `screenshot.png`, `visible_text.txt`, `features_json.json`
   - May contain `html_gz.html.gz` if conditional rules triggered

5. Check artifacts in database:
   ```bash
   curl http://localhost:8000/audits/{session_id}/artifacts
   ```

The session status should be `completed` if both desktop and mobile viewports succeeded,
or `partial`/`failed` if one or both failed.

For now, service dependencies are installed from `api/requirements.txt` and
`worker/requirements.txt`. The long-term source of truth will remain the
per-service `pyproject.toml` files.
