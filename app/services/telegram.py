# -*- coding: utf-8 -*-
"""
Backend'dan Telegram foydalanuvchisiga xabar yuborish. Bu bot process
(polling/webhook) ishlab turishini talab qilmaydi -- Telegram Bot API'ning
sendMessage endpoint'iga oddiy HTTP so'rov, chat_id sifatida User.telegram_id
ishlatiladi (u faqat foydalanuvchi botga /start bosib telefon raqamini
yuborgandan keyin to'ldiriladi -- bot/handlers/contact.py'ga qarang).
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger("omrmeroj.telegram")


async def send_telegram_message(chat_id: str, text: str) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN sozlanmagan -- xabar yuborilmadi")
        return False

    url = f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": text})
        if resp.status_code != 200:
            logger.error("Telegram sendMessage xato: %s %s", resp.status_code, resp.text)
            return False
        return True
    except httpx.HTTPError:
        logger.exception("Telegram sendMessage so'rovida tarmoq xatosi")
        return False
