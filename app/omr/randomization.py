# -*- coding: utf-8 -*-
"""
Har bir talaba uchun individual booklet yaratishda ishlatiladigan
randomizatsiya mantig'i (TZ 9-bo'lim).

Qoida:
  - Savollarning KO'RSATILISH TARTIBI (pozitsiyasi) faqat bir xil FAN
    ichida aralashtiriladi. Joriy sxemada har bir fan bloki (masalan
    Tarix 1-30) allaqachon bitta ball qiymatiga tegishli, shuning uchun
    "fan bloki ichida aralashtirish" aynan TZ talab qilgan "faqat bir
    xil ball (score_group) ichida aralashtirish" qoidasiga teng keladi.
  - A/B/C/D javob variantlari har bir savol uchun ALOHIDA va ERKIN
    aralashtiriladi.
  - Hammasi bitta seed'dan olingan random.Random orqali -- shu bilan
    aralashtirish istalgan payt REPRODUCIBLE (masalan booklet PDF'ni
    qayta generatsiya qilish yoki natijani tekshirish uchun).
"""
from __future__ import annotations

import random

LETTERS = ["A", "B", "C", "D"]


def _group_into_blocks(questions: list[dict]) -> list[list[dict]]:
    """Savollarni asl `tartib` bo'yicha saralab, ketma-ket bir xil
    (fan, ball) segmentlariga bo'ladi."""
    ordered = sorted(questions, key=lambda q: q["tartib"])
    blocks: list[list[dict]] = []
    current: list[dict] = []
    current_key = None
    for q in ordered:
        key = (q["fan"], q["ball"])
        if key != current_key and current:
            blocks.append(current)
            current = []
        current_key = key
        current.append(q)
    if current:
        blocks.append(current)
    return blocks


def build_shuffled_booklet(questions: list[dict], seed: str) -> tuple[list[dict], dict]:
    """
    questions -- bitta Variant'ga tegishli savollar, har biri:
        {id, tartib, fan, ball, savol_html, savol_rasm_url, jadval_html,
         variant_a_html, variant_b_html, variant_c_html, variant_d_html,
         togri_javob}
    seed -- masalan f"{exam_id}-{booklet_id}".

    Qaytaradi:
        rendered_questions -- display_tartib bo'yicha o'sish tartibida,
            har biri {display_tartib, fan, ball, savol_html,
            savol_rasm_url, jadval_html, options:[{"letter","html"}, ...]}
        answer_key -- omr_service.py kutayotgan formatda:
            {str(display_tartib): {"fan", "ball",
             "correct_letter_shown_to_student",
             "letter_to_original_option", "original_question_id"}}
    """
    rng = random.Random(seed)
    blocks = _group_into_blocks(questions)

    rendered: list[dict] = []
    answer_key: dict[str, dict] = {}

    for block in blocks:
        positions = [q["tartib"] for q in block]  # slotlar (1-30 va h.k.) o'zgarmaydi
        shuffled_questions = block[:]
        rng.shuffle(shuffled_questions)

        for position, q in zip(positions, shuffled_questions):
            option_texts = [q["variant_a_html"], q["variant_b_html"], q["variant_c_html"], q["variant_d_html"]]
            order = list(range(4))
            rng.shuffle(order)

            options = [
                {"letter": LETTERS[shown_pos], "html": option_texts[orig_idx]}
                for shown_pos, orig_idx in enumerate(order)
            ]

            togri_idx = "ABCD".index(q["togri_javob"].upper())
            correct_shown_letter = LETTERS[order.index(togri_idx)]
            letter_to_original_option = {LETTERS[shown_pos]: orig_idx for shown_pos, orig_idx in enumerate(order)}

            rendered.append({
                "display_tartib": position,
                "fan": q["fan"],
                "ball": q["ball"],
                "savol_html": q["savol_html"],
                "savol_rasm_url": q.get("savol_rasm_url"),
                "jadval_html": q.get("jadval_html"),
                "options": options,
            })

            answer_key[str(position)] = {
                "fan": q["fan"],
                "ball": q["ball"],
                "correct_letter_shown_to_student": correct_shown_letter,
                "savol_html": q.get("savol_html", ""),  # QO'SHING
                "variant_a_html": q.get("variant_a_html", ""),  # QO'SHING
                "variant_b_html": q.get("variant_b_html", ""),  # QO'SHING
                "variant_c_html": q.get("variant_c_html", ""),  # QO'SHING
                "variant_d_html": q.get("variant_d_html", ""),  # QO'SHING
                "letter_to_original_option": letter_to_original_option,
                "original_question_id": q["id"],
            }

    rendered.sort(key=lambda x: x["display_tartib"])
    return rendered, answer_key