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
