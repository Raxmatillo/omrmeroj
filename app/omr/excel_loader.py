# -*- coding: utf-8 -*-
"""
savollar_shabloni.xlsx faylini o'qib, generate_question_booklet.py kutayotgan
formatga o'tkazadi. Bu qism -- o'qituvchi yuklagan Excel bilan booklet
generatori orasidagi "ko'prik".
"""

from app.utils.excel_shared import (
    read_and_validate_rows,
    ExcelValidationError as TemplateError,  # eski nom bilan moslik uchun
    LETTER_TO_INDEX,
)

__all__ = ["load_questions_from_excel", "TemplateError"]


def load_questions_from_excel(path, sheet_name="Savollar"):
    rows, warnings = read_and_validate_rows(path, sheet_name=sheet_name)

    questions = []
    for position, row in enumerate(rows, start=1):
        questions.append({
            "id": position,
            "fan": row["fan"],
            "ball": f"{row['ball']:g}",
            "savol": row["savol"],
            "variantlar": row["variantlar"],
            "togri_index": LETTER_TO_INDEX[row["togri_letter"]],
        })

    return questions, warnings