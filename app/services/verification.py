# -*- coding: utf-8 -*-
"""
Telefon tasdiqlash kodlarini yaratish -- YAGONA joy.

Ilgari bu mantiq ikki joyda mustaqil yozilgan edi:
  - app/routers/auth.py -> _create_and_queue_code() (cooldown TEKSHIRADI)
  - bot/handlers/contact.py -> create_verification_code() (cooldown TEKSHIRMAYDI)

Natijada foydalanuvchi botga kontaktni qayta-qayta yuborib, cheksiz
kod so'rashi mumkin edi. Endi ikkalasi ham shu bitta funksiyani
chaqiradi -- cooldown har doim, har ikkala oqimda ham amal qiladi.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.security import generate_verification_code, hash_code


class VerificationCooldownError(Exception):
    """Cooldown tugamagan -- bot uchun (HTTPException API-ga xos bo'lgani uchun)."""

    def __init__(self, wait_seconds: int):
        self.wait_seconds = wait_seconds
        super().__init__(f"Cooldown: {wait_seconds}s qoldi")


def create_and_queue_code(db: Session, phone: str, purpose: str = "register") -> str:
    """Cooldownni tekshiradi, yangi kod yaratib DB'ga yozadi va uni
    (hali yubormasdan) qaytaradi."""
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
        raise VerificationCooldownError(max(wait_seconds, 1))

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


def create_and_queue_code_or_raise_http(db: Session, phone: str, purpose: str = "register") -> str:
    """API router'lar uchun -- cooldown buzilsa HTTPException(429) ko'taradi
    (auth.py'dagi eski xatti-harakat bilan bir xil)."""
    try:
        return create_and_queue_code(db, phone, purpose)
    except VerificationCooldownError as e:
        raise HTTPException(
            status_code=429,
            detail=f"Iltimos {e.wait_seconds} soniyadan keyin qayta urining",
        )