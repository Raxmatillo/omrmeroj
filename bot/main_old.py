# -*- coding: utf-8 -*-
"""
Telegram bot -- alohida process sifatida ishga tushadi:

    python -m bot.main

FastAPI backend (app/main.py) bilan bitta DB'ni bo'lishadi, lekin
mustaqil hayot tsikliga ega (long polling). Productionda buni systemd
service (yoki Docker container) sifatida ishga tushiring -- pastdagi
README bo'limiga qarang.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from bot.handlers import contact, omr, orders, start, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("omrmeroj.bot")


async def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN .env faylida to'ldirilmagan -- @BotFather'dan "
            "token oling va .env'ga qo'shing."
        )

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(contact.router)
    dp.include_router(omr.router)
    dp.include_router(orders.router)  # YANGI -- buyurtmalar navbati

    # Agar avval webhook o'rnatilgan bo'lsa, polling bilan ziddiyat
    # bo'lmasligi uchun tozalab tashlaymiz.
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Bot polling boshlandi")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())


