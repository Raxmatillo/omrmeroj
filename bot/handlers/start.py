# -*- coding: utf-8 -*-
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message):
    # Start parametrini olish (agar kelgan bo'lsa)
    args = message.text.split()
    phone_param = args[1] if len(args) > 1 else None

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text="📱 Telefon raqamni yuborish",
                request_contact=True
            )]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    if phone_param:
        # Telefon raqam parametr sifatida kelgan (change-phone oqimi)
        await message.answer(
            f"👋 Assalomu alaykum!\n\n"
            f"📱 Siz <b>{phone_param}</b> raqamini yangilamoqchisiz.\n"
            f"Tasdiqlash uchun quyidagi tugma orqali <b>yangi raqam</b> ulangan "
            f"SIM-kartadan kontaktingizni yuboring.\n\n"
            f"⚠️ <i>Kod faqat shu raqam uchun yuboriladi.</i>",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "👋 <b>Assalomu alaykum!</b>\n\n"
            "🎓 <b>OMR Meroj</b> – imtihonlarni avtomatik tekshirish tizimi.\n\n"
            "📌 Tizimga kirish yoki roʻyxatdan oʻtish uchun pastdagi tugma "
            "orqali <b>Telefon raqamingizni</b> yuboring.\n\n"
            "🔐 Bu raqam sizning <b>shaxsiy identifikatoringiz</b> boʻlib, "
            "barcha imtihon natijalari shu raqamga bogʻlanadi.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )