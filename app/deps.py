# -*- coding: utf-8 -*-
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import decode_access_token
from app import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token yaroqsiz yoki muddati tugagan",
    )
    payload = decode_access_token(token)
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
