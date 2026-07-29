# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
    generate_verification_code,
    hash_code,
    verify_code_hash,
)
from app.services.telegram import send_telegram_message

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------
# Ichki yordamchi funksiyalar
# ---------------------------------------------------------------------

def _create_and_queue_code(db: Session, phone: str, purpose: str) -> str:
    """Cooldown'ni tekshiradi, yangi kod yaratib DB'ga yozadi va uni
    (hali yubormasdan) qaytaradi -- chaqiruvchi shu kodni Telegram orqali
    yuboradi."""
    cooldown = timedelta(seconds=settings.VERIFICATION_CODE_RESEND_COOLDOWN_SECONDS)
    last = (
        db.query(models.PhoneVerificationCode)
        .filter(
            models.PhoneVerificationCode.phone == phone,
            models.PhoneVerificationCode.purpose == purpose,
        )
        .order_by(models.PhoneVerificationCode.created_at.desc())
        .first()
    )
    if last and datetime.utcnow() - last.created_at < cooldown:
        wait_seconds = int((cooldown - (datetime.utcnow() - last.created_at)).total_seconds())
        raise HTTPException(
            status_code=429,
            detail=f"Iltimos {max(wait_seconds, 1)} soniyadan keyin qayta urining",
        )

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

# (bu kod sizda allaqachon bor, faqat ishlatilish tartibi)
@router.post("/register-request", response_model=schemas.RequestCodeOut)
async def register_request(payload: schemas.RegisterRequestIn, db: Session = Depends(get_db)):
    # Telefon raqam tekshiriladi
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if user:
        if user.is_verified:
            raise HTTPException(status_code=400, detail="Bu raqam allaqachon faollashtirilgan")
        if user.telegram_id:
            # Agar telegram_id mavjud bo'lsa, demak kontakt yuborilgan
            raise HTTPException(status_code=400, detail="Bu raqam allaqachon bog'langan")
    
    # Yangi user yaratamiz yoki mavjudini yangilaymiz
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
    
    # KOD YUBORILMAYDI! Faqat botga havola
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


# ---------------------------------------------------------------------
# LOGIN (telefon + parol)
# ---------------------------------------------------------------------

@router.post("/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user or not verify_password(payload.password, user.password_hash):
        print("User: ", user)
        print("User password hash:", user.password_hash)
        print(verify_password(payload.password, user.password_hash))
        print("Payload: ", payload)
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
    sent = await send_telegram_message(
        user.telegram_id,
        f"Parolni tiklash kodi: {code}\n"
        f"Kod {settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa amal qiladi. Hech kimga bermang.",
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