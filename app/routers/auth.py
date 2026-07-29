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


@router.post("/dev-register", response_model=schemas.UserOut)
def dev_register(payload: schemas.DevRegisterIn, db: Session = Depends(get_db)):
    """
    FAQAT DEV_MODE=True bo'lganda ishlaydi. Productionda DEV_MODE=False
    qilinadi -- ro'yxatdan o'tish endi Telegram bot orqali (/start ->
    telefon raqam yuborish) amalga oshadi, bu endpoint faqat lokal
    testlash uchun qoladi.
    """
    if not settings.DEV_MODE:
        raise HTTPException(status_code=403, detail="Dev-register o'chirilgan")

    existing = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bu raqam bilan foydalanuvchi mavjud")

    user = models.User(
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=models.UserRole(payload.role),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, db: Session = Depends(get_db)):
    """Parol bilan kirish -- asosan superadmin yoki parol bilan yaratilgan
    akkauntlar uchun. Telegram orqali bog'langan teacher akkauntlarida
    password_hash ishlatib bo'lmaydigan qiymat bilan yaratiladi (pastga
    qarang), shuning uchun ular faqat /auth/request-code +
    /auth/verify-code orqali kiradi."""
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Telefon raqami yoki parol xato")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akkaunt faol emas")
    token = create_access_token(user.id, user.role.value)
    return schemas.TokenOut(access_token=token)


@router.post("/request-code", response_model=schemas.RequestCodeOut)
async def request_code(payload: schemas.RequestCodeIn, db: Session = Depends(get_db)):
    """
    Mobil ilova shu endpointni chaqiradi. Foydalanuvchi avval Telegram
    botga /start bosib telefon raqamini yubormagan bo'lsa (ya'ni
    telegram_id bog'lanmagan bo'lsa) kod yuborilmaydi -- avval botda
    ro'yxatdan o'tish talab qilinadi.
    """
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user or not user.telegram_id:
        raise HTTPException(
            status_code=404,
            detail="Bu raqam Telegram botga ulanmagan. Avval botda /start bosib ro'yxatdan o'ting.",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akkaunt faol emas")

    cooldown = timedelta(seconds=settings.VERIFICATION_CODE_RESEND_COOLDOWN_SECONDS)
    last = (
        db.query(models.PhoneVerificationCode)
        .filter(models.PhoneVerificationCode.phone == payload.phone)
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
        phone=payload.phone,
        code_hash=hash_code(code),
        expires_at=datetime.utcnow() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES),
    )
    db.add(record)
    db.commit()

    sent = await send_telegram_message(
        user.telegram_id,
        f"Kirish kodingiz: {code}\n"
        f"Kod {settings.VERIFICATION_CODE_TTL_MINUTES} daqiqa amal qiladi. Hech kimga bermang.",
    )
    if not sent:
        raise HTTPException(status_code=502, detail="Telegram orqali kod yuborib bo'lmadi, birozdan keyin urinib ko'ring")

    return schemas.RequestCodeOut(sent=True, detail="Kod Telegram botga yuborildi")


@router.post("/verify-code", response_model=schemas.TokenOut)
def verify_code(payload: schemas.VerifyCodeIn, db: Session = Depends(get_db)):
    invalid = HTTPException(status_code=400, detail="Kod noto'g'ri yoki muddati tugagan")

    record = (
        db.query(models.PhoneVerificationCode)
        .filter(
            models.PhoneVerificationCode.phone == payload.phone,
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

    if not verify_code_hash(payload.code, record.code_hash):
        record.attempts += 1
        db.commit()
        raise invalid

    record.is_used = True
    db.commit()

    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Akkaunt faol emas")

    token = create_access_token(user.id, user.role.value)
    return schemas.TokenOut(access_token=token)


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user
