# bot/handlers/contact.py
# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app import models
from app.security import generate_verification_code, hash_code
from bot.services.user_service import (
    PhoneAlreadyLinkedError,
    link_telegram_contact,
    get_user_by_phone,
)

logger = logging.getLogger("omrmeroj.bot.contact")
router = Router(name="contact")


def create_verification_code(db: Session, phone: str, purpose: str = "register") -> str:
    """Kod yaratib, DB ga saqlaydi"""
    # Eski kodlarni o'chirish (ixtiyoriy)
    # db.query(models.PhoneVerificationCode).filter(
    #     models.PhoneVerificationCode.phone == phone,
    #     models.PhoneVerificationCode.purpose == purpose,
    #     models.PhoneVerificationCode.is_used == False
    # ).update({"is_used": True})
    
    code = generate_verification_code()
    record = models.PhoneVerificationCode(
        phone=phone,
        code_hash=hash_code(code),
        purpose=purpose,
        expires_at=datetime.utcnow() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES),
    )
    db.add(record)
    db.commit()
    return code


@router.message(F.contact)
async def handle_contact(message: Message):
    contact = message.contact
    
    # Faqat o'z raqamini yuborishga ruxsat
    if contact.user_id != message.from_user.id:
        await message.answer(
            "Iltimos, faqat o'zingizning telefon raqamingizni yuboring.",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    
    db = SessionLocal()
    try:
        # 1. Telefon raqamini tekshiramiz (saytda ro'yxatdan o'tganmi?)
        user = get_user_by_phone(db, contact.phone_number)
        
        if not user:
            await message.answer(
                "❌ Bu telefon raqam bilan ro'yxatdan o'tilmagan.\n"
                "Iltimos, avval saytda ro'yxatdan o'ting: https://your-domain.com/register",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        
        # 2. Parol saqlanganmi? (saytda ro'yxatdan o'tgan)
        if not user.password_hash:
            await message.answer(
                "❌ Avval saytda parol yarating!",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        
        # 3. Allaqachon faollashtirilganmi?
        if user.is_verified:
            await message.answer(
                "✅ Bu raqam allaqachon faollashtirilgan.\n"
                "Saytga kirish uchun telefon va parolingizdan foydalaning.",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        
        # 4. Telegram ID ni bog'laymiz (agar bog'lanmagan bo'lsa)
        if not user.telegram_id:
            user.telegram_id = str(message.from_user.id)
            db.commit()
        
        # 5. KOD YARATAMIZ (aynan shu yerda!)
        code = create_verification_code(db, contact.phone_number, purpose="register")
        
        # 6. Kodni botda ko'rsatamiz (inline tugma bilan)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="📋 Kodni nusxalash",
                    callback_data=f"copy_{code}"
                )]
            ]
        )
        
        await message.answer(
            f"✅ Telefon raqamingiz tasdiqlandi!\n\n"
            f"🔐 Tasdiqlash kodingiz: <b>{code}</b>\n\n"
            f"⏳ Kod {settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa amal qiladi.\n"
            f"📋 Kodni nusxalash uchun tugmani bosing va saytga kiriting.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        # Klaviaturani olib tashlaymiz
        await message.answer(
            "Endi saytga qaytib, ushbu kodni kiriting va hisobingizni faollashtiring.",
            reply_markup=ReplyKeyboardRemove()
        )
        
    except PhoneAlreadyLinkedError:
        await message.answer(
            "⚠️ Bu telefon raqami boshqa Telegram akkauntga ulangan.\n"
            "Yordam uchun administratorga murojaat qiling.",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.exception("Contact'ni qayta ishlashda xato")
        await message.answer(
            "❌ Kutilmagan xatolik yuz berdi. Iltimos, birozdan keyin qayta urinib ko'ring.",
            reply_markup=ReplyKeyboardRemove()
        )
    finally:
        db.close()


# Kodni nusxalash uchun callback handler
@router.callback_query(lambda c: c.data and c.data.startswith("copy_"))
async def copy_code_callback(callback):
    code = callback.data.split("_")[1]
    await callback.answer(f"✅ Kod nusxalandi: {code}", show_alert=True)