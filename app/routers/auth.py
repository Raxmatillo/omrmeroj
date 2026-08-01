# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_internal_secret
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
    generate_verification_code,
    hash_code,
    verify_code_hash,
)
from app.services.telegram import send_telegram_message
from app.services.verification import create_and_queue_code_or_raise_http as _create_and_queue_code

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------
# Ichki yordamchi funksiyalar
# ---------------------------------------------------------------------


def _consume_valid_code(db: Session, phone: str, code: str, purpose: str) -> None:
    """Berilgan kod shu telefon+purpose uchun to'g'ri va amal qilayotgan
    bo'lsa -- is_used=True qilib belgilaydi. Aks holda 400 qaytaradi."""
    invalid = HTTPException(status_code=400, detail="Kod noto'g'ri yoki muddati tugagan")

    record = (
        db.query(models.PhoneVerificationCode)
        .filter(
            models.PhoneVerificationCode.phone == phone,
            models.PhoneVerificationCode.purpose == purpose,
            models.PhoneVerificationCode.is_used.is_(False),
        )
        .order_by(models.PhoneVerificationCode.created_at.desc())
        .first()
    )
    if not record:
        raise invalid
    if record.expires_at < datetime.utcnow():
        raise invalid
    if record.attempts >= settings.VERIFICATION_CODE_MAX_ATTEMPTS:
        raise invalid
    if not verify_code_hash(code, record.code_hash):
        record.attempts += 1
        db.commit()
        raise invalid

    record.is_used = True
    db.commit()


NOT_LINKED_DETAIL = (
    "Bu raqam Telegram botga ulanmagan. Avval botda /start bosib "
    "telefon raqamingizni yuboring."
)


# ---------------------------------------------------------------------
# RO'YXATDAN O'TISH
# ---------------------------------------------------------------------
#
# Oqim:
#   1) Foydalanuvchi botga /start bosib "Telefon yuborish" tugmasi orqali
#      kontakt yuboradi (bot/handlers/contact.py) -- shu bosqichda User
#      qatori yaratiladi (telegram_id bilan), lekin is_verified=False,
#      password_hash esa vaqtinchalik tasodifiy qiymat.
#   2) Sayt: POST /auth/register-request { phone, password, full_name }
#      -- haqiqiy parolni saqlaydi va botga tasdiqlash kodi yuboradi.
#   3) Sayt: POST /auth/register-verify { phone, code } -- kod to'g'ri
#      bo'lsa is_verified=True qilib, token qaytaradi (avtomatik login).
#
@router.post("/dev-register", response_model=schemas.TokenOut)
def dev_register(payload: schemas.RegisterRequestIn, db: Session = Depends(get_db)):
    if not settings.DEV_MODE:
        raise HTTPException(status_code=404, detail="Not Found")

    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    
    # AGAR FOYDALANUVCHI ALLAQACHON MAVJUD VA FAOLLASHTIRILGAN BO'LSA
    if user and user.is_verified:
        raise HTTPException(
            status_code=400, 
            detail="Ushbu telefon raqami orqali allaqachon ro'yxatdan o'tilgan. Iltimos, tizimga kiring."
        )

    if not user:
        user = models.User(
            phone=payload.phone,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
            is_verified=True,
            is_active=True,
        )
        db.add(user)
    else:
        user.full_name = payload.full_name
        user.password_hash = hash_password(payload.password)
        user.is_verified = True

    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.role.value)
    return schemas.TokenOut(access_token=token)


@router.post("/register-request", response_model=schemas.RequestCodeOut)
async def register_request(payload: schemas.RegisterRequestIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    
    # Tekshiruv tartibi to'g'rilandi:
    if user:
        if user.is_verified:
            raise HTTPException(
                status_code=400, 
                detail="Ushbu telefon raqami allaqachon ro'yxatdan o'tgan va faollashtirilgan. Tizimga kiring."
            )
        if user.telegram_id:
            # Bot orqali raqam bog'langan, lekin hali kod tasdiqlanmagan bo'lsa
            raise HTTPException(
                status_code=400, 
                detail="Bu raqam botga bog'langan, iltimos kelgan kodni kiriting yoki qayta botdan kod oling."
            )

    # Yangi user yaratamiz yoki vaqtinchalik hisobni yangilaymiz
    if not user:
        user = models.User(
            phone=payload.phone,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
            is_verified=False,
            is_active=True,
            telegram_id=None,
        )
        db.add(user)
    else:
        user.full_name = payload.full_name
        user.password_hash = hash_password(payload.password)
        user.is_verified = False
        user.telegram_id = None
        
    db.commit()

    return schemas.RequestCodeOut(
        sent=False,
        detail="Iltimos, botga o'tib telefon raqamingizni yuboring: @merojuzbot"
    )
@router.post("/register-verify", response_model=schemas.TokenOut)
def register_verify(payload: schemas.RegisterVerifyIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    _consume_valid_code(db, payload.phone, payload.code, purpose="register")

    user.is_verified = True
    db.commit()

    token = create_access_token(user.id, user.role.value)
    return schemas.TokenOut(access_token=token)

@router.post("/change-phone-request", response_model=schemas.RequestCodeOut)
def change_phone_request(
    payload: schemas.ChangePhoneRequestIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Telefon raqamni almashtirish -- 1-bosqich. Bu yerda kod DARHOL
    yaratilmaydi (parol/ismni o'zgartirishdan farqli, chunki yangi
    raqamning HAQIQIY egasi ekanini faqat Telegram tasdiqlashi mumkin).
    Kod bot orqali -- foydalanuvchi shu yangi raqam ulangan Telegram
    hisobidan kontakt yuborganda -- yaratiladi (bot/handlers/contact.py).
    """
    if payload.new_phone == user.phone:
        raise HTTPException(status_code=400, detail="Bu allaqachon sizning joriy raqamingiz")

    existing = db.query(models.User).filter(models.User.phone == payload.new_phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bu telefon raqami boshqa hisobga tegishli")

    return schemas.RequestCodeOut(
        sent=False,
        detail=(
            "Iltimos, Telegram botga o'ting va yangi raqamingiz ulangan "
            "SIM-kartadan kontaktni yuboring -- bot sizga tasdiqlash "
            "kodini yuboradi."
        ),
    )


@router.post("/change-phone-verify", response_model=schemas.UserOut)
def change_phone_verify(
    payload: schemas.ChangePhoneVerifyIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _consume_valid_code(db, payload.new_phone, payload.code, purpose="change_phone")

    # Race-condition himoyasi: kod yaratilgandan keyin ham raqam band bo'lib qolgan bo'lishi mumkin
    existing = db.query(models.User).filter(models.User.phone == payload.new_phone).first()
    if existing and existing.id != user.id:
        raise HTTPException(status_code=400, detail="Bu telefon raqami boshqa hisobga tegishli")

    user.phone = payload.new_phone
    db.commit()
    db.refresh(user)
    return user

# ---------------------------------------------------------------------
# LOGIN (telefon + parol)
# ---------------------------------------------------------------------

@router.post("/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Telefon raqami yoki parol xato")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akkaunt faol emas")
    if not user.is_verified:
        raise HTTPException(
            status_code=403,
            detail="Ro'yxatdan o'tish yakunlanmagan -- avval /auth/register-verify orqali kodni tasdiqlang",
        )
    token = create_access_token(user.id, user.role.value)
    return schemas.TokenOut(access_token=token)


# ---------------------------------------------------------------------
# PAROLNI UNUTDIM
# ---------------------------------------------------------------------

@router.post("/forgot-password", response_model=schemas.RequestCodeOut)
async def forgot_password(payload: schemas.ForgotPasswordIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user or not user.telegram_id:
        raise HTTPException(status_code=404, detail=NOT_LINKED_DETAIL)
    if not user.is_verified:
        raise HTTPException(status_code=400, detail="Bu raqam hali ro'yxatdan o'tmagan.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akkaunt faol emas")

    code = _create_and_queue_code(db, user.phone, purpose="reset_password")
    
    from app.services.telegram import make_copy_button_keyboard, send_telegram_message
    
    reply_markup = make_copy_button_keyboard(code, purpose="reset_password", phone=user.phone)
    
    text = (
        f"🔐 <b>Parolni tiklash so'rovi</b>\n\n"
        f"📱 Telefon raqam: <code>{user.phone}</code>\n"
        f"🔑 <b>Tasdiqlash kodi:</b> <code>{code}</code>\n\n"
        f"⏳ Kod <b>{settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa</b> amal qiladi.\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>MUHIM!</b> Agar bu Siz boshlamagan bo'lmasangiz,"
        f"bu xabarni <b>E'TIBORSIZ QOLDIRING</b> va hech kimga kodni bermang.\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 Saytga qaytib, ushbu kodni kiriting va parolni yangilang."
    )
    
    sent = await send_telegram_message(
        user.telegram_id,
        text,
        reply_markup=reply_markup,
    )
    
    if not sent:
        raise HTTPException(status_code=502, detail="Telegram orqali kod yuborib bo'lmadi, birozdan keyin urinib ko'ring")

    return schemas.RequestCodeOut(sent=True, detail="Kod Telegram botga yuborildi")

@router.post("/reset-password", response_model=schemas.TokenOut)
def reset_password(payload: schemas.ResetPasswordIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    _consume_valid_code(db, payload.phone, payload.code, purpose="reset_password")

    user.password_hash = hash_password(payload.new_password)
    db.commit()

    token = create_access_token(user.id, user.role.value)
    return schemas.TokenOut(access_token=token)


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.put("/me", response_model=schemas.UserOut)
def update_profile(payload: schemas.ProfileUpdateIn,
                    user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.full_name is not None:
        user.full_name = payload.full_name
    db.commit()
    db.refresh(user)
    return user


@router.post("/change-password", response_model=schemas.TokenOut)
def change_password(payload: schemas.ChangePasswordIn,
                     user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Joriy parol noto'g'ri")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    token = create_access_token(user.id, user.role.value)
    return schemas.TokenOut(access_token=token)


# Delete account
@router.post("/delete-account-request", response_model=schemas.RequestCodeOut)
async def delete_account_request(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Hisobni o'chirish so'rovi. Telegram orqali tasdiqlash kodi yuboriladi.
    """
    if not user.telegram_id:
        raise HTTPException(
            status_code=400,
            detail="Telegram bog'lanmagan. Iltimos, avval botga o'tib, telefon raqamingizni yuboring."
        )
    
    code = _create_and_queue_code(db, user.phone, purpose="delete_account")
    
    from app.services.telegram import make_copy_button_keyboard, send_telegram_message
    
    reply_markup = make_copy_button_keyboard(code, purpose="delete_account", phone=user.phone)
    
    text = (
        f"🗑️ <b>Hisobni o'chirish so'rovi</b>\n\n"
        f"📱 Telefon raqam: <code>{user.phone}</code>\n"
        f"🔐 <b>Tasdiqlash kodi:</b> <code>{code}</code>\n\n"
        f"⏳ Kod <b>{settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa</b> amal qiladi.\n\n"
        f"⚠️ <b>DIQQAT!</b> Hisobni o'chirish bilan quyidagi ma'lumotlar butunlay yo'qoladi:\n"
        f"• Guruhlar va o'quvchilar\n"
        f"• Testlar va variantlar\n"
        f"• Imtihonlar va natijalar\n"
        f"• Barcha yuklangan fayllar\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>MUHIM!</b> Agar bu Siz boshlamagan bo'lmasangiz,"
        f"bu xabarni <b>E'TIBORSIZ QOLDIRING</b> va hech kimga kodni bermang.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 Saytga qaytib, ushbu kodni kiriting va hisobni o'chirishni yakunlang."
    )
    
    sent = await send_telegram_message(user.telegram_id, text, reply_markup)
    if not sent:
        raise HTTPException(status_code=502, detail="Telegram orqali kod yuborib bo'lmadi, birozdan keyin urinib ko'ring")
    
    return schemas.RequestCodeOut(sent=True, detail="Tasdiqlash kodi Telegram botga yuborildi")


# auth.py

@router.post("/cancel-code", dependencies=[Depends(require_internal_secret)])
def cancel_code(payload: schemas.CancelCodeIn, db: Session = Depends(get_db)):
    """FAQAT bot (server-to-server, X-Internal-Secret orqali) chaqirishi
    mumkin -- foydalanuvchi login qilmagan bosqichda ham (masalan
    registratsiya kodini bekor qilishda) ishlashi kerak bo'lgani uchun
    JWT talab qila olmaydi. Shu sababli require_internal_secret orqali
    himoyalangan -- aks holda istalgan kishi faqat telefon raqamni
    bilib, boshqa foydalanuvchining kutayotgan kodini bekor qila olardi."""
    record = (
        db.query(models.PhoneVerificationCode)
        .filter(
            models.PhoneVerificationCode.phone == payload.phone,
            models.PhoneVerificationCode.purpose == payload.purpose,
            models.PhoneVerificationCode.is_used.is_(False),
        )
        .order_by(models.PhoneVerificationCode.created_at.desc())
        .first()
    )

    if record:
        record.is_used = True
        db.commit()
        return {"ok": True, "message": "Kod bekor qilindi"}

    return {"ok": False, "message": "Kod topilmadi"}

@router.post("/delete-account-confirm")
async def delete_account_confirm(
    payload: schemas.DeleteAccountConfirmIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Hisobni o'chirishni tasdiqlash. Kodni tekshiradi va barcha ma'lumotlarni o'chiradi.
    """
    _consume_valid_code(db, user.phone, payload.code, purpose="delete_account")
    
    # Foydalanuvchini va unga tegishli barcha ma'lumotlarni o'chirish
    from app.services.account_service import delete_user_account
    delete_user_account(db, user)
    
    return {"ok": True, "message": "Hisob muvaffaqiyatli o'chirildi"}