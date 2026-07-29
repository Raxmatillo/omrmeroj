# -*- coding: utf-8 -*-
"""
O'zbekiston mobil raqamlarini formatga tekshiradi.

MUHIM: bu faqat FORMAT (operator kodi + uzunlik) tekshiruvi. Raqamning
haqiqatan ham "tirik" ekanini SMS orqali emas, balki bot orqali bilamiz --
foydalanuvchi shu raqamga bog'langan Telegram akkaunt bilan "Telefon
yuborish" tugmasini bossagina (bot/handlers/contact.py -> contact.phone_number)
raqam haqiqiy hisoblanadi, chunki uni Telegram allaqachon tasdiqlagan.
"""
import re

_UZ_OPERATOR_CODES = (
    "90", "91", "93", "94", "95", "97", "98", "99",
    "33", "88",
    "20", "77", "78", "79",
)

_UZ_PHONE_RE = re.compile(r"^\+998(" + "|".join(_UZ_OPERATOR_CODES) + r")\d{7}$")


def normalize_phone(phone: str) -> str:
    p = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not p.startswith("+"):
        p = "+" + p.lstrip("0")
    return p


def validate_uzbek_phone(phone: str) -> str:
    normalized = normalize_phone(phone)
    if not _UZ_PHONE_RE.match(normalized):
        raise ValueError(
            "Telefon raqam O'zbekiston formatida bo'lishi kerak, masalan: +998901234567"
        )
    return normalized