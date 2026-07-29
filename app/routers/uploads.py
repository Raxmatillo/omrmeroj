# -*- coding: utf-8 -*-
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app import models
from app.config import settings
from app.deps import require_teacher

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_SIZE_MB = 5


@router.post("/question-image")
async def upload_question_image(file: UploadFile = File(...), user: models.User = Depends(require_teacher)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Faqat PNG/JPEG/WEBP rasm qabul qilinadi")

    content = await file.read()
    if len(content) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"Rasm {MAX_SIZE_MB}MB dan kichik bo'lishi kerak")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4()}.{ext}"

    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
        url = _upload_to_supabase(filename, content, file.content_type)
    else:
        # DEV FALLBACK -- lokal papkaga saqlaydi. Supabase sozlanganda
        # bu tarmoq avtomatik chetlab o'tiladi, boshqa hech narsa
        # o'zgarmaydi (chaqiruvchi kod faqat qaytgan URL bilan ishlaydi).
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        path = os.path.join(settings.UPLOAD_DIR, filename)
        with open(path, "wb") as f:
            f.write(content)
        url = f"/uploads/files/{filename}"

    return {"url": url}


def _upload_to_supabase(filename: str, content: bytes, content_type: str) -> str:
    import httpx

    upload_url = f"{settings.SUPABASE_URL}/storage/v1/object/{settings.SUPABASE_BUCKET}/{filename}"
    resp = httpx.post(
        upload_url,
        headers={
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "Content-Type": content_type,
        },
        content=content,
        timeout=30,
    )
    if resp.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Supabase yuklashda xato: {resp.text}")
    return f"{settings.SUPABASE_URL}/storage/v1/object/public/{settings.SUPABASE_BUCKET}/{filename}"
