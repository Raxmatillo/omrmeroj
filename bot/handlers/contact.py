# -*- coding: utf-8 -*-
import logging
import base64
import httpx
from aiogram.types import CallbackQuery



from aiogram import F, Router
from aiogram.types import (
    Message,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CopyTextButton,
)
from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.config import settings
from app.database import SessionLocal
from app import models
from bot.services.user_service import (
    PhoneAlreadyLinkedError,
    link_telegram_contact,
    get_user_by_phone,
)
from app.utils.phone import normalize_phone
from app.services.verification import (
    create_and_queue_code_or_raise_http as create_verification_code,
)

logger = logging.getLogger("omrmeroj.bot.contact")
router = Router(name="contact")


def _code_keyboard(code: str, purpose: str, phone: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Kodni nusxalash",
                    callback_data=f"copy_{code}",
                    copy_text=CopyTextButton(text=code),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bu men emasman",
                    callback_data=f"not_me_{purpose}_{phone}",  # ✅ to'g'ri
                )
            ]
        ]
    )

@router.message(F.contact)
async def handle_contact(message: Message):
    contact = message.contact

    # Faqat o'z raqamini yuborishga ruxsat
    if contact.user_id != message.from_user.id:
        await message.answer(
            f"✅ <b>Telefon raqam tasdiqlandi!</b>\n\n"
            f"📱 Raqam: <code>{phone}</code>\n"
            f"🔐 <b>Tasdiqlash kodi:</b> <code>{code}</code>\n\n"
            f"⏳ Kod <b>{settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa</b> amal qiladi.\n"
            f"📋 Kodni nusxalash uchun tugmani bosing va saytga kiriting.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ <b>MUHIM!</b> Agar bu Siz boshlamagan bo'lmasangiz,"
            f"bu xabarni <b>E'TIBORSIZ QOLDIRING</b> va hech kimga kodni bermang.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 <a href='https://your-domain.com/verify'>Kodni kiritish sahifasiga o'tish</a>",
            reply_markup=_code_keyboard(code, purpose="register", phone=phone),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    db = SessionLocal()
    try:
        phone = normalize_phone(contact.phone_number)

        # ------------------------------------------------------------------
        # 0-BOSQICH: TELEFON RAQAMNI ALMASHTIRISH SO'ROVI
        # ------------------------------------------------------------------
        # ------------------------------------------------------------------
# 0-BOSQICH: TELEFON RAQAMNI ALMASHTIRISH SO'ROVI
# ------------------------------------------------------------------
        linked_user = db.query(models.User).filter(
            models.User.telegram_id == str(message.from_user.id)
        ).first()

        if linked_user and linked_user.phone != phone:
            # Bu raqam boshqa birov tomonidan egallanmaganligini tekshiramiz
            other_owner = get_user_by_phone(db, phone)
            if other_owner and other_owner.id != linked_user.id:
                await message.answer(
                    "❌ <b>Xatolik</b>\n\n"
                    "Bu telefon raqami boshqa hisobga tegishli.\n"
                    "Iltimos, boshqa raqam yoki o'z raqamingizni yuboring.",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="HTML",
                )
                return

            try:
                code = create_verification_code(db, phone, purpose="change_phone")
            except HTTPException as e:
                await message.answer(
                    f"⏳ <b>Kutish vaqti</b>\n\n{e.detail}",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="HTML",
                )
                return

            await message.answer(
                f"🔄 <b>Raqamni oʻzgartirish so'rovi</b>\n\n"
                f"📱 Yangi raqam: <code>{phone}</code>\n"
                f"🔐 <b>Tasdiqlash kodi:</b> <code>{code}</code>\n\n"
                f"⏳ Kod <b>{settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa</b> amal qiladi.\n"
                f"📌 Saytga qaytib, ushbu kodni kiriting va raqamni yangilang.\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ <b>MUHIM!</b> Agar bu Siz boshlamagan bo'lmasangiz,"
                f"bu xabarni <b>E'TIBORSIZ QOLDIRING</b> va hech kimga kodni bermang.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━",
                reply_markup=_code_keyboard(code, purpose="change_phone", phone=phone),  # <-- BU YERDA purpose
                parse_mode="HTML",
            )
            await message.answer(
                "💡 <i>Klaviaturani yopish uchun bu xabarni e'tiborsiz qoldiring.</i>",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
            )
            return

        # ------------------------------------------------------------------
        # 1-BOSQICH: ODDIY RO'YXATDAN O'TISH TASDIQLASH
        # ------------------------------------------------------------------

        user = get_user_by_phone(db, phone)

        if not user:
            await message.answer(
                "❌ <b>Ro'yxatdan o'tilmagan</b>\n\n"
                "Bu telefon raqam bilan tizimda hisob topilmadi.\n\n"
                "📌 Iltimos, avval <b>saytda ro'yxatdan o'ting</b>:\n"
                "🔗 <a href='https://your-domain.com/register'>https://your-domain.com/register</a>",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return

        if not user.password_hash:
            await message.answer(
                "⚠️ <b>Parol mavjud emas</b>\n\n"
                "Saytda ro'yxatdan o'tganingizda parol yaratishingiz kerak.\n"
                "📌 Iltimos, <b>saytga kiring</b> va parolni o'rnating.",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
            )
            return

        if user.is_verified:
            await message.answer(
                "✅ <b>Hisob allaqachon faollashtirilgan</b>\n\n"
                "🔑 Saytga kirish uchun telefon raqam va parolingizdan foydalaning.\n\n"
                "📌 <a href='https://your-domain.com/login'>Kirish sahifasiga o'tish</a>",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return

        # Telegram ID ni bog'laymiz
        if not user.telegram_id:
            user.telegram_id = str(message.from_user.id)
            db.commit()

        try:
            code = create_verification_code(db, phone, purpose="register")
        except HTTPException as e:
            await message.answer(
                f"⏳ <b>Kutish vaqti</b>\n\n{e.detail}",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
            )
            return

        await message.answer(
            f"✅ <b>Telefon raqam tasdiqlandi!</b>\n\n"
            f"📱 Raqam: <code>{phone}</code>\n"
            f"🔐 <b>Tasdiqlash kodi:</b> <code>{code}</code>\n\n"
            f"⏳ Kod <b>{settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa</b> amal qiladi.\n"
            f"📋 Kodni nusxalash uchun tugmani bosing va saytga kiriting.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ <b>MUHIM!</b> Agar bu Siz boshlamagan bo'lmasangiz,"
            f"bu xabarni <b>E'TIBORSIZ QOLDIRING</b> va hech kimga kodni bermang.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 <a href='https://your-domain.com/verify'>Kodni kiritish sahifasiga o'tish</a>",
            reply_markup=_code_keyboard(code, purpose="register"),  # <-- BU YERDA purpose
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        await message.answer(
            "💡 <i>Klaviaturani yopish uchun bu xabarni e'tiborsiz qoldiring.</i>",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )


    except PhoneAlreadyLinkedError:
        await message.answer(
            "⚠️ <b>Telefon raqami allaqachon bog'langan</b>\n\n"
            "Bu raqam boshqa Telegram akkauntga ulangan.\n"
            "Yordam uchun administratorga murojaat qiling.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Contact'ni qayta ishlashda xato")
        await message.answer(
            "❌ <b>Kutilmagan xatolik</b>\n\n"
            "Iltimos, birozdan keyin qayta urinib ko'ring.\n"
            "Agar muammo davom etsa, yordam xizmatiga murojaat qiling.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
    finally:
        db.close()


# ---------- CALLBACK HANDLERS ----------
@router.callback_query(lambda c: c.data and c.data.startswith("copy_"))
async def copy_code_callback(callback):
    code = callback.data.split("_", 1)[1]
    await callback.answer(f"✅ Kod nusxalandi: {code}", show_alert=True)



@router.callback_query(lambda c: c.data and c.data.startswith("not_me_"))
async def not_me_callback(callback: CallbackQuery):
    """
    "Bu men emasman" tugmasi bosilganda ishga tushadi.
    Kodni bekor qiladi va xabarni o'chiradi.
    """
    data = callback.data  # not_me_me_reset_password_+998941010133
    print('data: ', data)
    # 1-usul: not_me_ dan keyin kelganini olamiz
    # "not_me_me_reset_password_+998941010133" -> "me_reset_password_+998941010133"
    rest = data.replace("not_me_", "", 1)  # not_me_ ni olib tashlaymiz

    last_underscore = rest.rfind("_")  # oxirgi _ indeksi
    if last_underscore == -1:
        await callback.answer("❌ Xatolik yuz berdi.", show_alert=True)
        return




    purpose = rest[:last_underscore]  # "reset_password"
    phone = rest[last_underscore + 1:]  # "+998941010133"


    print(f"🔍 not_me_callback: purpose={purpose}, phone={phone}")


    # 2. Backendga bekor qilish so'rovini yuborish
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                f"{settings.BACKEND_URL}/auth/cancel-code",
                json={"phone": phone, "purpose": purpose}
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    await callback.answer(
                        "✅ Kod bekor qilindi",
                        show_alert=True
                    )
                    # Xabarni o'chiramiz
                    await callback.message.delete()
                else:
                    await callback.answer(
                        "⚠️ Kod allaqachon bekor qilingan yoki topilmadi.",
                        show_alert=True
                    )
            else:
                await callback.answer(
                    f"❌ Server xatosi: {resp.status_code}",
                    show_alert=True
                )
        except httpx.TimeoutException:
            await callback.answer(
                "⏳ Server javob bermadi, qayta urinib ko'ring.",
                show_alert=True
            )
        except Exception as e:
            logger.exception("not_me_callback xatosi")
            await callback.answer(
                "❌ Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
                show_alert=True
            )


@router.callback_query(lambda c: c.data == "help_code")
async def help_code_callback(callback):
    await callback.answer(
        "📌 Kodni nusxalash uchun tugmani bosing.\n"
        "Keyin saytga o'tib, kodni kiriting.",
        show_alert=True,
    )