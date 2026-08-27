# app/routers/system.py
"""
Dastur va internet holatini tekshirish uchun endpoint.

Bu router LOGIN TALAB QILMAYDI -- chunki login sahifasida ham
"internet bormi" degan holatni ko'rsatishimiz kerak (masalan,
telefon tasdiqlash kodi bot orqali kelmasligi mumkinligini oldindan
bildirish uchun).

Tekshiruv Telegram API'ga qisqa HEAD so'rov yuborish orqali amalga
oshiriladi -- bu aynan dasturning internetga muhtoj bo'lgan yagona
tashqi bog'lanishi (bot orqali tasdiqlash kodlari + Supabase'ga rasm
yuklash). Natija bir necha soniya keshlanadi, shunda frontend har necha
soniyada so'rov yuborsa ham tarmoqqa haddan tashqari ko'p chiqilmaydi.
"""
import time
import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])

_CACHE_TTL_SECONDS = 8.0
_CHECK_TIMEOUT_SECONDS = 2.5
_CHECK_URL = "https://api.telegram.org"

_cache: dict = {"internet": None, "checked_at": 0.0}


async def _check_internet() -> bool:
    now = time.monotonic()
    if _cache["internet"] is not None and (now - _cache["checked_at"]) < _CACHE_TTL_SECONDS:
        return _cache["internet"]

    ok = False
    try:
        async with httpx.AsyncClient(timeout=_CHECK_TIMEOUT_SECONDS) as client:
            resp = await client.head(_CHECK_URL, follow_redirects=True)
            ok = resp.status_code < 500
    except httpx.HTTPError:
        ok = False

    _cache["internet"] = ok
    _cache["checked_at"] = now
    return ok


@router.get("/status")
async def get_system_status():
    internet = await _check_internet()
    return {
        # Bu maydon javob kelgani bilanoq "ok" -- chunki javob kelayotgan
        # bo'lsa, demak backend jarayoni ishlab turibdi.
        "app": "ok",
        "internet": internet,
    }