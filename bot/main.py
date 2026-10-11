# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime

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
    dp.include_router(orders.router)

    await bot.delete_webhook(drop_pending_updates=True)

    # ─── ADMINGA "BOT ISHGA TUSHDI" XABARI ───────────────────
    if settings.ADMIN_TELEGRAM_CHAT_ID:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await bot.send_message(
                chat_id=settings.ADMIN_TELEGRAM_CHAT_ID,
                text=(
                    "🟢 <b>Bot ishga tushdi</b>\n\n"
                    f"🕐 Vaqt: <code>{now}</code>\n"
                    f"🖥 Rejim: <b>Desktop / Production</b>\n"
                    f"✅ Polling boshlandi"
                ),
            )
            logger.info(f"✅ Adminga xabar yuborildi: {settings.ADMIN_TELEGRAM_CHAT_ID}")
        except Exception as e:
            logger.error(f"❌ Adminga xabar yuborilmadi: {e}")
    else:
        logger.warning("⚠️ ADMIN_TELEGRAM_CHAT_ID yo'q -- xabar yuborilmadi")

    logger.info("Bot polling boshlandi")
    try:
        await dp.start_polling(bot)
    finally:
        # ─── BOT TO'XTaganda ham adminga xabar (ixtiyoriy) ───
        if settings.ADMIN_TELEGRAM_CHAT_ID:
            try:
                await bot.send_message(
                    chat_id=settings.ADMIN_TELEGRAM_CHAT_ID,
                    text="🔴 <b>Bot to'xtadi</b>",
                )
            except Exception:
                pass
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())