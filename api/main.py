"""
FastAPI application entrypoint for the AI Website Audit API.

This module sets up the FastAPI app, configures logging, and registers
route handlers.
"""

from __future__ import annotations

import os
import threading
import logging
from html import escape as html_escape
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import asyncio
import requests

from api.routes import audits
from shared.config import get_config
from shared.logging import configure_logging, get_logger
from shared.telegram import send_telegram_document, send_telegram_message
from api.db import get_db_session
from api.repositories.audit_repository import AuditRepository
from api.services.audit_service import AuditService
from shared.db import get_db_session as shared_get_db_session

load_dotenv()


def _build_excel_rubric_download_url(*, base_url: str | None, session_id: str) -> str | None:
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/audits/{session_id}/report/excel"


def _normalize_list_domain(arg: str) -> str | None:
    raw = (arg or "").strip()
    if not raw:
        return None

    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        host = parsed.netloc
    else:
        host = raw

    if not host:
        return None

    host = host.strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _format_created_at(value: object) -> str:
    if hasattr(value, "strftime"):
        return str(value.strftime("%Y-%m-%d %H:%M:%S"))
    return str(value)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_config()
    logger = get_logger(__name__)

    # Configure structured logging
    log_level = logging.getLevelName(config.log_level.upper())
    configure_logging(
        level=log_level,
        log_file=config.log_file,
        log_stdout=config.log_stdout,
        log_format=config.log_format,
        telegram_bot_token=config.telegram_bot_token,
        telegram_chat_id=config.telegram_chat_id,
        telegram_log_every_event=config.telegram_log_every_event,
    )

    app = FastAPI(
        title="AI Website Audit API",
        description="API for creating and querying website audit sessions",
        version="0.1.0",
    )

    # CORS middleware (permissive for MVP; tighten in production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route handlers
    app.include_router(audits.router)

    @app.get("/health")
    def health_check():
        """Health check endpoint."""
        return {"status": "ok"}

    @app.post("/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        db: Session = Depends(get_db_session),
    ) -> dict:
        """
        Telegram command handler (OPTIONAL).

        Commands supported:
        - /start <url_or_domain>  -> enqueue audit and reply with session_id
        - /get <session_id>       -> reply with current session status
        - /info                    -> reply with command help
        """
        config = get_config()
        if not config.telegram_bot_token:
            raise HTTPException(status_code=503, detail="TELEGRAM_BOT_TOKEN not configured")

        payload = await request.json()
        update = payload.get("message") or payload.get("edited_message") or {}
        message = update or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()

        if not chat_id or not text:
            return {"ok": True}

        def _reply(msg: str) -> None:
            try:
                send_telegram_message(
                    bot_token=config.telegram_bot_token,  # type: ignore[arg-type]
                    chat_id=str(chat_id),
                    message=msg,
                    parse_mode="HTML",
                )
            except Exception:
                pass

        try:
            command, _, arg = text.partition(" ")
            command = command.lower().strip()
            # Normalize commands like "/info!" -> "/info"
            while command and command[-1] in {"!", ".", "?", ","}:
                command = command[:-1].strip()
            arg = (arg or "").strip()

            logger.info(
                "telegram_command_received",
                telegram_command=command,
                telegram_chat_id=str(chat_id),
            )

            repository = AuditRepository(db)
            service = AuditService(repository)

            if command == "/info":
                _reply(
                    "Commands:\n"
                    "/run <code>site-domain-or-url</code>\n"
                    "/get <code>session_id</code>\n"
                    "/list <code>site-domain</code>\n"
                )
                return {"ok": True}

            if command in {"/start", "/run"}:
                if not arg:
                    _reply("Usage: /run <code>site-domain-or-url</code>")
                    return {"ok": True}

                normalized = arg
                if not normalized.startswith(("http://", "https://")):
                    normalized = f"https://{normalized.lstrip('/')}"

                resp = service.create_audit_session(
                    url=normalized,
                    mode="standard",
                )
                _reply(
                    f"✅ Audit queued\n"
                    f"Session: <code>{resp.id}</code>\n"
                    f"Status: <code>{resp.status}</code>"
                )
                return {"ok": True}

            if command == "/get":
                if not arg:
                    _reply("Usage: /get <code>session_id</code>")
                    return {"ok": True}

                from uuid import UUID

                try:
                    session_uuid = UUID(arg)
                except Exception:
                    _reply("Invalid session_id format. Expected UUID.")
                    return {"ok": True}

                session = service.get_audit_session(session_uuid)
                if session is None:
                    _reply(f"Session not found: <code>{arg}</code>")
                    return {"ok": True}

                artifacts = service.get_audit_artifacts(session_uuid)
                excel_artifact = next(
                    (a for a in artifacts or [] if a.type == "excel_rubric_xlsx"),
                    None,
                )
                excel_ready = excel_artifact is not None

                auth_required = bool(config.api_secret_key and config.api_secret_key.strip())
                can_link = not auth_required
                excel_url = (
                    _build_excel_rubric_download_url(
                        base_url=config.report_base_url,
                        session_id=str(session.id),
                    )
                    if can_link
                    else None
                )

                err = session.error_summary or "—"
                err_safe = html_escape(err)

                if excel_ready and excel_url:
                    excel_line = f'Excel rubric: <a href="{html_escape(excel_url)}">Download XLSX</a>'
                elif excel_ready:
                    excel_line = "Excel rubric: ready. XLSX will be sent to you."
                else:
                    excel_line = "Excel rubric: not ready yet."

                _reply(
                    f"ℹ️ Session status\n"
                    f"Session: <code>{session.id}</code>\n"
                    f"Status: <code>{session.status}</code>\n"
                    f"Error: <code>{err_safe}</code>\n"
                    f"{excel_line}"
                )

                if excel_ready and not excel_url:
                    excel_path = Path(config.artifacts_dir) / str(excel_artifact.storage_uri)
                    sent = send_telegram_document(
                        bot_token=config.telegram_bot_token,  # type: ignore[arg-type]
                        chat_id=str(chat_id),
                        document_path=str(excel_path),
                        filename=f"audit_rubric_{session.id}.xlsx",
                    )
                    if not sent:
                        _reply("Failed to send XLSX. You can try again later.")

                return {"ok": True}

            if command == "/list":
                if not arg:
                    _reply("Usage: /list <code>site-domain</code>")
                    return {"ok": True}

                domain = _normalize_list_domain(arg)
                if not domain:
                    _reply("Invalid domain. Usage: /list <code>site-domain</code>")
                    return {"ok": True}

                results = service.list_audit_sessions_by_domain(domain=domain, limit=501)
                truncated = len(results) > 500
                if truncated:
                    results = results[:500]

                if not results:
                    _reply(f"No audits found for <code>{html_escape(domain)}</code>.")
                    return {"ok": True}

                header = (
                    f"Audits for <code>{html_escape(domain)}</code>\n"
                    f"Showing <code>{len(results)}</code> most recent sessions"
                    f"{' (truncated)' if truncated else ''}:\n"
                )

                lines = [
                    f"- <code>{html_escape(str(r['id']))}</code> "
                    f"ran=<code>{html_escape(_format_created_at(r.get('created_at')))}</code> "
                    f"status=<code>{html_escape(str(r.get('status') or '—'))}</code>"
                    for r in results
                ]

                max_chars = 3900
                chunks: list[str] = []
                current = ""
                for line in lines:
                    candidate = f"{current}\n{line}" if current else line
                    if len(candidate) > max_chars:
                        if current:
                            chunks.append(current)
                        current = line
                    else:
                        current = candidate
                if current:
                    chunks.append(current)

                for idx, chunk in enumerate(chunks, start=1):
                    if idx == 1:
                        _reply(f"{header}{chunk}")
                    else:
                        _reply(f"{chunk}")
                return {"ok": True}

            # Unknown command
            _reply("Unknown command. Send /info for usage.")
            return {"ok": True}
        except Exception:
            _reply("Failed to process command.")
            raise HTTPException(status_code=400, detail="Failed to process command")

    return app


def _maybe_start_telegram_long_polling(app: FastAPI) -> None:
    config = get_config()
    if not config.telegram_bot_token:
        return

    enabled_raw = (os.getenv("TELEGRAM_LONG_POLLING_ENABLED") or "false").strip().lower()
    enabled = enabled_raw in {"1", "true", "yes", "y", "on"}
    if not enabled:
        return

    stop_event = threading.Event()

    def _run_loop() -> None:
        offset: int = 0
        while not stop_event.is_set():
            try:
                url = f"https://api.telegram.org/bot{config.telegram_bot_token}/getUpdates"
                params = {"timeout": 30, "offset": offset, "allowed_updates": ["message"]}
                resp = requests.get(url, params=params, timeout=40)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger = get_logger(__name__)
                logger.warning(
                    "telegram_long_polling_error",
                    error=str(e),
                    telegram_chat_id=config.telegram_chat_id,
                )
                stop_event.wait(5)
                continue

            for update in data.get("result") or []:
                chat_id: int | None = None
                try:
                    update_id = int(update.get("update_id"))
                    offset = update_id + 1
                    message = update.get("message") or update.get("edited_message") or {}
                    chat = message.get("chat") or {}
                    chat_id = chat.get("id")
                    text = (message.get("text") or "").strip()
                    if not chat_id or not text:
                        continue

                    repository_db = None
                    with shared_get_db_session() as db:
                        repository_db = AuditRepository(db)
                        service = AuditService(repository_db)

                        def _reply(msg: str) -> None:
                            try:
                                send_telegram_message(
                                    bot_token=config.telegram_bot_token,  # type: ignore[arg-type]
                                    chat_id=str(chat_id),
                                    message=msg,
                                    parse_mode="HTML",
                                )
                            except Exception:
                                return

                        command, _, arg = text.partition(" ")
                        command = command.lower().strip()
                        while command and command[-1] in {"!", ".", "?", ","}:
                            command = command[:-1].strip()
                        arg = (arg or "").strip()
                        logger_ = get_logger(__name__)
                        logger_.info(
                            "telegram_command_received",
                            telegram_command=command,
                            telegram_chat_id=str(chat_id),
                        )

                        if command == "/info":
                            _reply(
                                "Commands:\n"
                                "/run <code>site-domain-or-url</code>\n"
                                "/get <code>session_id</code>\n"
                                "/list <code>site-domain</code>\n"
                            )
                            continue

                        if command in {"/start", "/run"}:
                            if not arg:
                                _reply("Usage: /run <code>site-domain-or-url</code>")
                                continue

                            normalized = arg
                            if not normalized.startswith(("http://", "https://")):
                                normalized = f"https://{normalized.lstrip('/')}"

                            resp2 = service.create_audit_session(
                                url=normalized,
                                mode="standard",
                            )
                            _reply(
                                f"✅ Audit queued\n"
                                f"Session: <code>{resp2.id}</code>\n"
                                f"Status: <code>{resp2.status}</code>"
                            )
                            continue

                        if command == "/get":
                            if not arg:
                                _reply("Usage: /get <code>session_id</code>")
                                continue

                            from uuid import UUID

                            try:
                                session_uuid = UUID(arg)
                            except Exception:
                                _reply("Invalid session_id format. Expected UUID.")
                                continue

                            session = service.get_audit_session(session_uuid)
                            if session is None:
                                _reply(f"Session not found: <code>{arg}</code>")
                                continue

                            artifacts = service.get_audit_artifacts(session_uuid)
                            excel_artifact = next(
                                (
                                    a
                                    for a in artifacts or []
                                    if a.type == "excel_rubric_xlsx"
                                ),
                                None,
                            )
                            excel_ready = excel_artifact is not None

                            err = session.error_summary or "—"
                            err_safe = html_escape(err)

                            auth_required = bool(
                                config.api_secret_key and config.api_secret_key.strip()
                            )
                            can_link = not auth_required
                            excel_url = (
                                _build_excel_rubric_download_url(
                                    base_url=config.report_base_url,
                                    session_id=str(session.id),
                                )
                                if can_link
                                else None
                            )

                            if excel_ready and excel_url:
                                excel_line = (
                                    f'Excel rubric: <a href="{html_escape(excel_url)}">Download XLSX</a>'
                                )
                            elif excel_ready:
                                excel_line = "Excel rubric: ready. XLSX will be sent to you."
                            else:
                                excel_line = "Excel rubric: not ready yet."

                            _reply(
                                f"ℹ️ Session status\n"
                                f"Session: <code>{session.id}</code>\n"
                                f"Status: <code>{session.status}</code>\n"
                                f"Error: <code>{err_safe}</code>\n"
                                f"{excel_line}"
                            )

                            if excel_ready and not excel_url:
                                excel_path = (
                                    Path(config.artifacts_dir)
                                    / str(excel_artifact.storage_uri)
                                )
                                sent = send_telegram_document(
                                    bot_token=config.telegram_bot_token,  # type: ignore[arg-type]
                                    chat_id=str(chat_id),
                                    document_path=str(excel_path),
                                    filename=f"audit_rubric_{session.id}.xlsx",
                                )
                                if not sent:
                                    _reply(
                                        "Failed to send XLSX. You can try again later."
                                    )

                            continue

                        if command == "/list":
                            if not arg:
                                _reply("Usage: /list <code>site-domain</code>")
                                continue

                            domain = _normalize_list_domain(arg)
                            if not domain:
                                _reply(
                                    "Invalid domain. Usage: /list <code>site-domain</code>"
                                )
                                continue

                            results = service.list_audit_sessions_by_domain(
                                domain=domain, limit=501
                            )
                            truncated = len(results) > 500
                            if truncated:
                                results = results[:500]

                            if not results:
                                _reply(
                                    f"No audits found for <code>{html_escape(domain)}</code>."
                                )
                                continue

                            header = (
                                f"Audits for <code>{html_escape(domain)}</code>\n"
                                f"Showing <code>{len(results)}</code> most recent sessions"
                                f"{' (truncated)' if truncated else ''}:\n"
                            )

                            lines = [
                                f"- <code>{html_escape(str(r['id']))}</code> "
                                f"ran=<code>{html_escape(_format_created_at(r.get('created_at')))}</code> "
                                f"status=<code>{html_escape(str(r.get('status') or '—'))}</code>"
                                for r in results
                            ]

                            max_chars = 3900
                            chunks: list[str] = []
                            current = ""
                            for line in lines:
                                candidate = (
                                    f"{current}\n{line}" if current else line
                                )
                                if len(candidate) > max_chars:
                                    if current:
                                        chunks.append(current)
                                    current = line
                                else:
                                    current = candidate
                            if current:
                                chunks.append(current)

                            for idx, chunk in enumerate(chunks, start=1):
                                if idx == 1:
                                    _reply(f"{header}{chunk}")
                                else:
                                    _reply(f"{chunk}")
                            continue

                        _reply("Unknown command. Send /info for usage.")
                except Exception as e:
                    logger_ = get_logger(__name__)
                    logger_.warning(
                        "telegram_long_polling_command_error",
                        error=str(e),
                    )
                    try:
                        if chat_id and config.telegram_bot_token:
                            send_telegram_message(
                                bot_token=config.telegram_bot_token,  # type: ignore[arg-type]
                                chat_id=str(chat_id),
                                message="Failed to process command.",
                            )
                    except Exception:
                        pass
                    continue

    app.state.telegram_polling_stop_event = stop_event
    app.state.telegram_polling_thread = threading.Thread(
        target=_run_loop,
        name="telegram_long_polling",
        daemon=True,
    )

    app.state.telegram_polling_thread.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        stop_event.set()


# Create the app instance
app = create_app()
_maybe_start_telegram_long_polling(app)
