# -*- coding: utf-8 -*-
"""
Excel'dan savollarni o'qib, Question qatorlariga (DB CRUD formatiga)
aylantiradi. Validatsiya mantig'i app/utils/excel_shared.py'da --
bu yerda faqat natija Question modeli kutgan shaklga o'giriladi.
"""
from app.utils.excel_shared import (
    read_and_validate_rows,
    ExcelValidationError as ExcelImportError,  # eski nom bilan moslik uchun
)

__all__ = ["parse_excel", "ExcelImportError"]


def parse_excel(file_obj, sheet_name="Savollar"):
    rows, _warnings = read_and_validate_rows(file_obj, sheet_name=sheet_name)

    return [
        {
            "fan": row["fan"],
            "ball": row["ball"],
            "savol_html": row["savol"],
            "variant_a_html": row["variantlar"][0],
            "variant_b_html": row["variantlar"][1],
            "variant_c_html": row["variantlar"][2],
            "variant_d_html": row["variantlar"][3],
            "togri_javob": row["togri_letter"],
        }
        for row in rows
    ]