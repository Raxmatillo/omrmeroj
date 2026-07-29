# -*- coding: utf-8 -*-
import logging

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove

from app.config import settings
from app.database import SessionLocal
from bot.services.user_service import (
    PhoneAlreadyLinkedError,
    create_login_code,
    link_telegram_contact,
)

logger = logging.getLogger("omrmeroj.bot.contact")
router = Router(name="contact")


@router.message(F.contact)
async def handle_contact(message: Message):
    contact = message.contact

    # Telegram'ning "request_contact" tugmasi orqali kelgan contact har doim
    # foydalanuvchining o'ziniki bo'ladi, lekin ehtiyot chorasi sifatida
    # tekshiramiz (masalan kimdir boshqa contact'ni forward qilsa).
    if contact.user_id != message.from_user.id:
        await message.answer(
            "Iltimos, faqat o'zingizning telefon raqamingizni pastdagi tugma orqali yuboring."
        )
        return

    db = SessionLocal()
    try:
        try:
            user = link_telegram_contact(
                db,
                phone=contact.phone_number,
                telegram_id=str(message.from_user.id),
                full_name=message.from_user.full_name,
            )
        except PhoneAlreadyLinkedError:
            await message.answer(
                "Bu telefon raqami boshqa Telegram akkauntga allaqachon ulangan. "
                "Yordam uchun administratorga murojaat qiling.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        code = create_login_code(db, user.phone)
    except Exception:
        logger.exception("Contact'ni qayta ishlashda xato")
        await message.answer(
            "Kutilmagan xatolik yuz berdi, birozdan keyin qayta urinib ko'ring.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    finally:
        db.close()

    await message.answer(
        "Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\n"
        f"Kirish kodingiz: <b>{code}</b>\n"
        f"Ushbu kodni ilovada kiriting ({settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa amal qiladi). "
        "Keyingi safar ilovadan \"Kod yuborish\" tugmasini bossangiz, kod yana shu botga keladi.",
        reply_markup=ReplyKeyboardRemove(),
    )
