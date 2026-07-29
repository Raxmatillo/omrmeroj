# -*- coding: utf-8 -*-
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import decode_access_token
from app import models

# HTTPBearer -- Swagger'da faqat bitta "token" maydoni chiqaradi.
# OAuth2PasswordBearer'dan farqli, username/password/client_id so'ramaydi,
# chunki bizda haqiqiy OAuth2 password-flow yo'q -- login JSON body orqali
# ishlaydi (/auth/login, /auth/verify-code).
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token yaroqsiz yoki muddati tugagan",
    )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token berilmagan (Authorization: Bearer <token>)",
        )

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise unauthorized
    user = db.get(models.User, payload.get("sub"))
    if not user or not user.is_active:
        raise unauthorized
    return user


def require_teacher(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role not in (models.UserRole.teacher, models.UserRole.superadmin):
        raise HTTPException(status_code=403, detail="Faqat teacher uchun")
    return user


def require_superadmin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != models.UserRole.superadmin:
        raise HTTPException(status_code=403, detail="Faqat superadmin uchun")
    return user