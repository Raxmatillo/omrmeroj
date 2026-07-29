# -*- coding: utf-8 -*-
"""
Bot bilan FastAPI backend bitta DB'ni bo'lishadi (monorepo, ikkalasi ham
app.database/app.models'dan foydalanadi). Shu sababli bu yerda HTTP orqali
emas, to'g'ridan-to'g'ri SQLAlchemy session bilan ishlaymiz.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.security import generate_verification_code, hash_code, hash_password


class PhoneAlreadyLinkedError(Exception):
    """Shu telefon raqami boshqa Telegram akkauntga allaqachon ulangan."""


def normalize_phone(phone: str) -> str:
    p = phone.strip().replace(" ", "").replace("-", "")
    if not p.startswith("+"):
        p = "+" + p.lstrip("0")
    return p


def link_telegram_contact(
    db: Session, phone: str, telegram_id: str, full_name: str | None
) -> models.User:
    """
    Foydalanuvchi botga /start bosib "telefon raqamni yuborish" tugmasi
    orqali contact yuborganda chaqiriladi. Agar shu raqam bilan User
    mavjud bo'lmasa -- yangi teacher akkaunt yaratiladi. Mavjud bo'lsa --
    telegram_id shu akkauntga bog'lanadi (agar u boshqa Telegram
    akkauntga allaqachon bog'lanmagan bo'lsa).
    """
    phone = normalize_phone(phone)
    user = db.query(models.User).filter(models.User.phone == phone).first()

    if user:
        if user.telegram_id and user.telegram_id != telegram_id:
            raise PhoneAlreadyLinkedError(phone)
        user.telegram_id = telegram_id
        if full_name and not user.full_name:
            user.full_name = full_name
    else:
        user = models.User(
            phone=phone,
            # Parol orqali kirish ishlatilmaydi -- shuning uchun hech qachon
            # mos kelmaydigan tasodifiy hash qo'yiladi (nullable=False
            # bo'lgani uchun bo'sh string emas, to'liq bcrypt hash).
            password_hash=hash_password(uuid.uuid4().hex),
            telegram_id=telegram_id,
            full_name=full_name,
            role=models.UserRole.teacher,
        )
        db.add(user)

    db.commit()
    db.refresh(user)
    return user


def create_login_code(db: Session, phone: str) -> str:
    code = generate_verification_code()
    record = models.PhoneVerificationCode(
        phone=phone,
        code_hash=hash_code(code),
        expires_at=datetime.utcnow() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES),
    )
    db.add(record)
    db.commit()
    return code

# bot/services/user_service.py

def get_user_by_phone(db: Session, phone: str):
    """Telefon raqam bo'yicha foydalanuvchini qaytaradi"""
    return db.query(models.User).filter(models.User.phone == phone).first()