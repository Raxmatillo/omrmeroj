# app/services/telegram.py
import base64
import logging
import json

import httpx

from app.config import settings

logger = logging.getLogger("omrmeroj.telegram")


def encode_phone(phone: str) -> str:
    """Telefon raqamni base64 da kodlaydi."""
    return base64.b64encode(phone.encode()).decode()


async def send_telegram_message(chat_id: str, text: str, reply_markup: dict | None = None) -> bool:
    """Telegram foydalanuvchisiga xabar yuboradi."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN sozlanmagan")
        return False

    url = f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.error("Telegram sendMessage xato: %s %s", resp.status_code, resp.text)
            return False
        return True
    except httpx.HTTPError:
        logger.exception("Telegram sendMessage so'rovida tarmoq xatosi")
        return False


def make_copy_button_keyboard(code: str, purpose: str, phone: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📋 Kodni nusxalash",
                    "callback_data": f"copy_{code}",
                    "copy_text": {"text": code}
                }
            ],
            [
                {
                    "text": "❌ Bu men emasman",
                    "callback_data": f"not_me_{purpose}_{phone}"  # ✅ to'g'ri
                }
            ]
        ]
    }