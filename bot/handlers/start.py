# -*- coding: utf-8 -*-
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="\U0001F4F1 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Assalomu alaykum!\n\n"
        "OMR Meroj tizimiga kirish uchun telefon raqamingizni pastdagi "
        "tugma orqali yuboring. Bu -- Telegram tomonidan tasdiqlangan "
        "raqamingiz bo'lishi kerak.",
        reply_markup=keyboard,
    )
