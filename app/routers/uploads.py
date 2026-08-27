# -*- coding: utf-8 -*-
import os
import uuid
import requests
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi import Query

from app import models
from app.config import settings
from app.deps import require_teacher

from app import models
from app.config import settings
from app.deps import require_teacher

import io
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_SIZE_MB = 5

# YANGI: past piksel kenglikdagi rasmlar PDF'da (savollar kitobchasida)
# xira/pikselli ko'rinadi, chunki max 95mm (~360px 96dpi da, lekin chop
# etish uchun amalda ancha yuqoriroq DPI kerak) joyga cho'ziladi. Shu
# sababli yuklashda kamida shu piksel kenglikdan past rasm uchun
# (bloklamasdan, faqat) ogohlantirish qaytariladi -- frontend buni
# o'qituvchiga ko'rsatib, "sifatliroq rasm tanlang" deyishi mumkin.
MIN_RECOMMENDED_WIDTH_PX = 500
router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_SIZE_MB = 5

def _check_image_quality(content: bytes) -> str | None:
    """Rasm piksel o'lchamini tekshiradi. Rasmni ochib bo'lmasa (masalan
    kutubxona muammosi) yuklashni TO'XTATMAYDI -- faqat ogohlantirish
    berilmaydi (None qaytadi)."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        width, _height = img.size
    except Exception:  # noqa: BLE001
        return None

    if width < MIN_RECOMMENDED_WIDTH_PX:
        return (
            f"Rasm kengligi past ({width}px) -- savollar kitobchasida xira "
            f"ko'rinishi mumkin. Kamida {MIN_RECOMMENDED_WIDTH_PX}px "
            f"kenglikdagi (yoki undan yuqori sifatli) rasm tavsiya etiladi."
        )
    return None


@router.post("/question-image")
async def upload_question_image(file: UploadFile = File(...), user: models.User = Depends(require_teacher)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Faqat PNG/JPEG/WEBP rasm qabul qilinadi")

    content = await file.read()
    if len(content) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"Rasm {MAX_SIZE_MB}MB dan kichik bo'lishi kerak")

    quality_warning = _check_image_quality(content)  # YANGI

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

    # YANGI: "warning" maydoni ixtiyoriy -- eski frontend uni e'tiborsiz
    # qoldiradi (mavjud consumerlar buzilmaydi), yangi frontend buni
    # ko'rsatib, o'qituvchiga sifatliroq rasm tanlashni tavsiya qilishi
    # mumkin.
    return {"url": url, "warning": quality_warning}


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


# ✅ YANGI: URL dan rasm yuklab olish
@router.post("/fetch-image")
async def fetch_image_from_url(
    url: str = Query(..., description="Rasm URL manzili"),
    user: models.User = Depends(require_teacher),
):
    # URL ni tozalash
    url = url.strip()
    # Backslash -> forward slash
    url = url.replace("\\", "/")
    # Ketma-ket slaslarni bittaga aylantirish (faqat protokoldan keyin)
    import re
    url = re.sub(r'(?<!:)/{2,}', '/', url)
    # Agar protokol bo'lmasa, qo'shish
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    url = re.sub(r'https?://+', lambda m: m.group(0)[:m.group(0).index('//')+2], url)

    try:
        # 1. URL dan rasmni yuklab olish
        response = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        response.raise_for_status()

        # 2. Content-type ni tekshirish
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Fayl rasm emas")

        # 3. Fayl kengaytmasi
        ext = content_type.split("/")[-1]
        if ext not in ["png", "jpeg", "jpg", "webp"]:
            ext = "jpg"

        filename = f"{uuid.uuid4()}.{ext}"
        content = response.content

        # 4. Saqlash
        if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
            file_url = _upload_to_supabase(filename, content, content_type)
        else:
            os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
            path = Path(settings.UPLOAD_DIR) / filename
            path.write_bytes(content)
            file_url = f"/uploads/files/{filename}"

        print(f"Rasm yuklandi: {file_url} (original URL: {url})")

        return {"url": file_url, "filename": filename}

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Rasm yuklab olinmadi: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server xatosi: {str(e)}")