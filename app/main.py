# -*- coding: utf-8 -*-
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.config import settings
from app.routers import auth, groups, tests, uploads, exams

# Hozircha Alembic migratsiyasiz -- jadvallar to'g'ridan-to'g'ri yaratiladi.
# Productionga chiqishdan oldin buni Alembic'ga almashtirish TAVSIYA ETILADI
# (schema o'zgarishlarini xavfsiz boshqarish uchun).
Base.metadata.create_all(bind=engine)

app = FastAPI(title="OMR Meroj API", version="0.1.0")

app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(tests.router)
app.include_router(uploads.router)
app.include_router(exams.router)

# Dev fallback rasm serving (Supabase ulanganda kerak bo'lmaydi)
import os
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads/files", StaticFiles(directory=settings.UPLOAD_DIR), name="uploaded-files")


@app.get("/")
def root():
    return {"status": "ok", "service": "omr-meroj-api"}
