# -*- coding: utf-8 -*-
"""
Savollar banki uchun Excel import.

Ustunlar tartibi (1-qator sarlavha):
    A - T/r
    B - Fan
    C - Kitob
    D - Bo'lim
    E - Savol matni
    F - A javob
    G - B javob
    H - C javob
    I - D javob
    J - To'g'ri javob (A/B/C/D)
    K - Rasm URL (ixtiyoriy)
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import load_workbook


class ExcelImportError(Exception):
    pass


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _newlines_to_br(text: str) -> str:
    """Excel'dagi \\n larni HTML <br> ga aylantiradi."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "<br>")


def parse_bank_excel(file_bytes: BytesIO) -> list[dict]:
    try:
        wb = load_workbook(file_bytes, data_only=True)
    except Exception as e:
        raise ExcelImportError(f"Excel faylni o'qib bo'lmadi: {e}")

    ws = wb.active
    if ws is None:
        raise ExcelImportError("Excel faylda faol varaq topilmadi")

    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        raise ExcelImportError("Excel faylda ma'lumot yo'q (faqat sarlavha)")

    # Sarlavhalarni o'qish (1-qator)
    headers = [
        str(h).strip().lower() if h is not None else ""
        for h in rows[0]
    ]

    def col(name_options: list[str]) -> int:
        """Ustun indeksini topish: avval aniq mos, keyin qismiy."""
        for name in name_options:
            for i, h in enumerate(headers):
                if h == name:
                    return i
        for name in name_options:
            for i, h in enumerate(headers):
                if name in h:
                    return i
        return -1

    col_tartib = col(["tartib", "no", "number"])
    col_fan = col(["fan"])
    col_kitob = col(["kitob"])
    col_bolim = col(["bolim", "bo'lim"])
    col_savol = col(["savol"])
    col_a = col(["variant_a"])
    col_b = col(["variant_b"])
    col_c = col(["variant_c"])
    col_d = col(["variant_d"])
    col_javob = col(["javob", "togri_javob", "to'g'ri javob"])
    col_rasm = col(["savol_rasm_url", "rasm_url", "rasm"])

    # Majburiy ustunlarni tekshirish
    if col_fan == -1:
        raise ExcelImportError("'fan' ustuni topilmadi")
    if col_savol == -1:
        raise ExcelImportError("'savol' ustuni topilmadi")
    if col_a == -1 or col_b == -1 or col_c == -1 or col_d == -1:
        raise ExcelImportError("Variantlar ustunlari (variant_a/b/c/d) topilmadi")
    if col_javob == -1:
        raise ExcelImportError("'javob' ustuni topilmadi")

    data_rows = rows[1:]
    parsed: list[dict] = []
    errors: list[str] = []

    for idx, row in enumerate(data_rows, start=2):
        try:
            def get(c: int):
                if c == -1 or c >= len(row):
                    return ""
                return _clean_cell(row[c])

            tartib_raw = row[col_tartib] if col_tartib != -1 and col_tartib < len(row) else None
            fan = get(col_fan)
            kitob = get(col_kitob)
            bolim = get(col_bolim)
            savol = get(col_savol)
            a = get(col_a)
            b = get(col_b)
            c = get(col_c)
            d = get(col_d)
            togri = get(col_javob).upper()
            rasm_url = get(col_rasm)

            # Bo'sh qatorni o'tkazib yuborish
            if not savol and not a and not b and not c and not d:
                continue

            if not fan:
                errors.append(f"{idx}-qator: 'Fan' bo'sh")
                continue
            if not savol:
                errors.append(f"{idx}-qator: 'Savol matni' bo'sh")
                continue

            # 1/2/3/4 ni A/B/C/D ga aylantirish
            if togri in ("1", "2", "3", "4"):
                togri = chr(64 + int(togri))

            if togri not in ("A", "B", "C", "D"):
                errors.append(
                    f"{idx}-qator: 'To'g'ri javob' A/B/C/D bo'lishi kerak (hozir: '{togri}')"
                )
                continue

            try:
                tartib = int(tartib_raw) if tartib_raw is not None else (idx - 1)
            except (TypeError, ValueError):
                tartib = idx - 1

            parsed.append({
                "tartib": tartib,
                "fan": fan,
                "kitob": kitob or None,
                "bolim": bolim or None,
                "savol_html": _newlines_to_br(savol),
                "variant_a_html": _newlines_to_br(a),
                "variant_b_html": _newlines_to_br(b),
                "variant_c_html": _newlines_to_br(c),
                "variant_d_html": _newlines_to_br(d),
                "togri_javob": togri,
                "savol_rasm_url": rasm_url or None,
            })
        except Exception as e:
            errors.append(f"{idx}-qator: {e}")

    if errors:
        raise ExcelImportError(
            f"{len(errors)} ta xatolik:\n" + "\n".join(errors[:10])
        )

    if not parsed:
        raise ExcelImportError("Excel faylda hech qanday savol topilmadi")

    return parsed