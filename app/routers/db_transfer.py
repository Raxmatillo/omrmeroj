# app/routers/db_transfer.py
# -*- coding: utf-8 -*-
"""
Shaxsiy noutbuk/kompyuter almashtirganda lokal SQLite bazasini
eksport/import qilish uchun -- FAQAT egasi (+998941010133) uchun ochiq.

Faqat SQLite bilan ishlaydi (DATABASE_URL sqlite:// bo'lganda).
Productionda (Postgres) bu endpoint ataylab ishlamaydi -- u yerda
har doim yagona, jonli baza bo'ladi, shaxsiy ko'chirish shart emas.
"""
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from app import models
from app.config import settings
from app.database import engine
from app.deps import get_current_user

router = APIRouter(prefix="/db", tags=["db-transfer"])

OWNER_PHONE = "+998941010133"

REQUIRED_TABLES = {"users", "exams", "exam_students", "questions", "groups"}


def require_owner(user: models.User = Depends(get_current_user)) -> models.User:
    if user.phone != OWNER_PHONE:
        raise HTTPException(status_code=403, detail="Bu funksiya faqat egasi uchun ochilgan")
    return user


def _sqlite_path() -> str:
    if not settings.DATABASE_URL.startswith("sqlite"):
        raise HTTPException(
            status_code=400,
            detail="Bu funksiya faqat lokal SQLite bilan ishlaydi (hozirgi DATABASE_URL boshqacha)",
        )
    return settings.DATABASE_URL.split("///", 1)[-1]


def _validate_sqlite_file(path: str) -> None:
    """Fayl haqiqiy va bizning schema'ga mos SQLite baza ekanini tekshiradi --
    shu bilan foydalanuvchi tasodifan/qasddan mos kelmaydigan fayl yuborsa
    aralashib ketmaydi, aniq xato bilan rad etiladi."""
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
    except sqlite3.DatabaseError as e:
        raise HTTPException(status_code=400, detail=f"Fayl yaroqsiz SQLite baza: {e}")

    missing = REQUIRED_TABLES - tables
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Bu fayl OMR Meroj bazasiga o'xshamaydi (yetishmayotgan jadvallar: {missing})",
        )


@router.get("/export")
def export_database(user: models.User = Depends(require_owner)):
    """Joriy SQLite baza faylini yuklab olish."""
    db_path = _sqlite_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Baza fayli topilmadi")

    filename = f"omrmeroj_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
    return FileResponse(db_path, media_type="application/octet-stream", filename=filename)


@router.post("/import")
async def import_database(
    file: UploadFile = File(...),
    user: models.User = Depends(require_owner),
):
    """
    Boshqa joydan olingan SQLite baza faylini yuklab, joriy bazani
    ALMASHTIRADI (merge emas -- shu bilan ID/qator to'qnashuvi va
    aralashib ketish xavfi bo'lmaydi). Almashtirishdan oldin joriy
    baza avtomatik zaxiraga olinadi.
    """
    db_path = _sqlite_path()

    if not file.filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise HTTPException(status_code=400, detail="Fayl .db/.sqlite kengaytmali bo'lishi kerak")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Bo'sh fayl yuborildi")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        _validate_sqlite_file(tmp_path)

        backup_dir = Path(settings.OUTPUT_DIR) / "db_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = None
        if os.path.exists(db_path):
            backup_path = backup_dir / f"before_import_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(db_path, backup_path)

        # Faol ulanishlarni yopamiz, so'ng faylni to'liq almashtiramiz
        engine.dispose()
        shutil.copy2(tmp_path, db_path)
    finally:
        os.unlink(tmp_path)

    return {
        "ok": True,
        "message": "Baza muvaffaqiyatli import qilindi va joriy baza bilan almashtirildi",
        "backup_saved_to": str(backup_path) if backup_path else None,
    }