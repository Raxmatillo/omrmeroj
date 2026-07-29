# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-register", response_model=schemas.UserOut)
def dev_register(payload: schemas.DevRegisterIn, db: Session = Depends(get_db)):
    """
    FAQAT DEV_MODE=True bo'lganda ishlaydi. Telegram bot orqali ro'yxatdan
    o'tish tayyor bo'lgach, bu endpoint productionda o'chirib qo'yiladi
    (yoki DEV_MODE=False qilinadi) va haqiqiy /auth/telegram/verify oqimi
    ishlatiladi.
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
    user = db.query(models.User).filter(models.User.phone == payload.phone).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Telefon raqami yoki parol xato")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akkaunt faol emas")
    token = create_access_token(user.id, user.role.value)
    return schemas.TokenOut(access_token=token)


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user
