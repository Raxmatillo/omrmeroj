# app/utils/phone.py
# -*- coding: utf-8 -*-
"""
O'zbekiston mobil raqamlarini formatga tekshiradi.
Operator kodlari .env dan o'qiladi.
"""
import re
from app.config import settings


def get_operator_codes() -> tuple:
    """.env dan operator kodlarini o'qiydi"""
    if settings.PHONE_ALLOWED_OPERATORS:
        return tuple(op.strip() for op in settings.PHONE_ALLOWED_OPERATORS.split(","))
    # Default qiymatlar (agar .env da bo'lmasa)
    return ("90", "91", "93", "94", "95", "97", "98", "99", "33", "88", "77", "50")


def get_phone_regex() -> re.Pattern:
    """Telefon regex patternini qaytaradi"""
    # Agar .env da PHONE_PATTERN berilgan bo'lsa, undan foydalanamiz
    if hasattr(settings, 'PHONE_PATTERN') and settings.PHONE_PATTERN:
        return re.compile(settings.PHONE_PATTERN)
    
    # Aks holda operator kodlaridan pattern yasaymiz
    operators = "|".join(get_operator_codes())
    return re.compile(r"^\+998(" + operators + r")\d{7}$")


def normalize_phone(phone: str) -> str:
    """Telefon raqamni standart formatga keltiradi"""
    # Bo'sh joy va maxsus belgilarni olib tashlash
    p = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    
    # + belgisini tekshirish
    if not p.startswith("+"):
        # Agar mamlakat kodi bo'lmasa, qo'shamiz
        if not p.startswith(settings.PHONE_COUNTRY_CODE):
            p = f"+{settings.PHONE_COUNTRY_CODE}{p.lstrip('0')}"
        else:
            p = f"+{p}"
    return p


def validate_uzbek_phone(phone: str) -> str:
    """Telefon raqamni tekshiradi va normallashtiradi"""
    normalized = normalize_phone(phone)
    pattern = get_phone_regex()
    
    if not pattern.match(normalized):
        operators = ", ".join(get_operator_codes())
        raise ValueError(
            f"Telefon raqam noto'g'ri formatda.\n"
            f"Namuna: +{settings.PHONE_COUNTRY_CODE}90XXXXXXX\n"
            f"Ruxsat etilgan operatorlar: {operators}"
        )
    return normalized


# Eski kod bilan moslik uchun (agar biron joyda ishlatilsa)
_UZ_OPERATOR_CODES = get_operator_codes()
_UZ_PHONE_RE = get_phone_regex()