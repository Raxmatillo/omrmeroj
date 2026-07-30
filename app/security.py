# -*- coding: utf-8 -*-
import secrets
from datetime import datetime, timedelta

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Telefon orqali kirish uchun bir martalik kod (Telegram bot bilan yuboriladi)
# ---------------------------------------------------------------------------

def generate_verification_code(length: int | None = None) -> str:
    """Kriptografik jihatdan xavfsiz tasodifiy raqamli kod (masalan '384021')."""
    length = length or settings.VERIFICATION_CODE_LENGTH
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_code(code: str) -> str:
    """Kodni DB'ga saqlashdan oldin hash qiladi -- DB sizib ketsa ham
    kodning o'zi ochilib qolmasligi uchun (parol hash bilan bir xil
    mexanizm, bcrypt)."""
    return pwd_context.hash(code)


def verify_code_hash(code: str, code_hash: str) -> bool:
    return pwd_context.verify(code, code_hash)


# ---------------------------------------------------------------------------
# Signed/expiring fayl havolalari (masalan natija PDF'ining QR kodi)
#
# TZ 29-bo'lim: "Generated files public URL orqali ochilmasin". Shu bilan
# birga natija PDF'ida QR kod bo'lishi kerak (havola sifatida). Bu ikkisini
# muvofiqlashtirish uchun: QR ichiga ochiq/doimiy URL emas, balki MUDDATI
# TUGAYDIGAN va faqat bitta resursga (result_id) tegishli bo'lgan imzolangan
# token qo'yiladi. Token muddati tugagach havola ishlamay qoladi -- bu ham
# xavfsizlik, ham "havola sifatida ishlatish" talabini qondiradi.
# ---------------------------------------------------------------------------

FILE_ACCESS_PURPOSE = "file_access"


def create_file_access_token(resource_id: str, days: int = 30) -> str:
    """`resource_id` (masalan Result.id) uchun muddati tugaydigan token
    yaratadi. Standart 30 kun -- agar fayl saqlash siyosati boshqacha
    bo'lsa (masalan generated files 7 kunda o'chirilsa), shu qiymatni
    moslashtiring."""
    expire = datetime.utcnow() + timedelta(days=days)
    payload = {"rid": resource_id, "purpose": FILE_ACCESS_PURPOSE, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_file_access_token(token: str) -> str | None:
    """Token amal qilayotgan bo'lsa resource_id (masalan result_id)ni
    qaytaradi, aks holda None (muddati tugagan / soxta / boshqa maqsad
    uchun yaratilgan token)."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
    if payload.get("purpose") != FILE_ACCESS_PURPOSE:
        return None
    return payload.get("rid")