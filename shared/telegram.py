"""
Telegram notification helper for sending messages to Telegram chat.

Used to send ChatGPT responses and important logs to Telegram.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    message: str,
    parse_mode: Optional[str] = None,
) -> bool:
    """
    Send a message to Telegram chat.

    Returns True if successful, False otherwise.
    """
    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"Failed to send Telegram message: {e}")
        return False


def send_telegram_json(
    bot_token: str,
    chat_id: str,
    title: str,
    data: dict,
) -> bool:
    """
    Send a formatted JSON message to Telegram.

    Formats the JSON nicely and sends with a title.
    If the message is too large (>4000 chars), splits into multiple messages.
    """
    if not bot_token or not chat_id:
        return False

    try:
        json_str = json.dumps(data, indent=2, ensure_ascii=False)

        max_length = 4000
        header = f"<b>{title}</b>\n\n"

        if len(json_str) + len(header) <= max_length:
            message = f"{header}<pre>{json_str}</pre>"
            return send_telegram_message(
                bot_token=bot_token,
                chat_id=chat_id,
                message=message,
                parse_mode="HTML",
            )
        else:
            send_telegram_message(
                bot_token=bot_token,
                chat_id=chat_id,
                message=f"{header}JSON is too large ({len(json_str)} chars). Sending in parts...",
                parse_mode="HTML",
            )

            chunk_size = max_length - len(header) - 50
            parts = [json_str[i : i + chunk_size] for i in range(0, len(json_str), chunk_size)]

            for i, part in enumerate(parts, 1):
                part_title = f"{title} (Part {i}/{len(parts)})"
                message = f"<b>{part_title}</b>\n\n<pre>{part}</pre>"
                if not send_telegram_message(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    message=message,
                    parse_mode="HTML",
                ):
                    return False

            return True
    except Exception as e:
        logger.warning(f"Failed to send Telegram JSON: {e}")
        return False
