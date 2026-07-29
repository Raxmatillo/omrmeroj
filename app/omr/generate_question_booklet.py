# -*- coding: utf-8 -*-
"""
Savollar kitobchasi (question booklet) generator -- sample with 3 real
questions, showing per-student answer-option shuffling. Same coordinate
system / print-safety approach as generate_answer_sheet.py.

Randomization rule (as specified): question POSITION only swaps with other
questions worth the same point value; answer LETTERS (A/B/C/D) always
shuffle freely per student. This sample has 1 question per point group, so
position-swapping isn't visible here -- only letter-shuffling is.
"""

import json
import random

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

PAGE_W, PAGE_H = A4


def y(top_offset_mm):
    return PAGE_H - top_offset_mm * mm


def x(left_offset_mm):
    return left_offset_mm * mm


def text(c, left_mm, top_mm, s, size=8, font="Helvetica", center=False, bold=False, gray=False):
    c.setFont("Helvetica-Bold" if bold else font, size)
    c.setFillColorRGB(0.35, 0.35, 0.35) if gray else c.setFillColorRGB(0, 0, 0)
    if center:
        c.drawCentredString(x(left_mm), y(top_mm), s)
    else:
        c.drawString(x(left_mm), y(top_mm), s)


def wrapped_text(c, left_mm, top_mm, s, max_width_mm, size=9.5, leading=4.6, bold=False):
    """Simple word-wrap for question/option text. Returns bottom offset used (mm)."""
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    words = s.split(" ")
    line = ""
    cur_top = top_mm
    max_w_pt = max_width_mm * mm
    for w in words:
        trial = (line + " " + w).strip()
        if c.stringWidth(trial, "Helvetica-Bold" if bold else "Helvetica", size) > max_w_pt and line:
            c.drawString(x(left_mm), y(cur_top), line)
            cur_top += leading
            line = w
        else:
            line = trial
    if line:
        c.drawString(x(left_mm), y(cur_top), line)
        cur_top += leading
    return cur_top


def box(c, left_mm, top_mm, w_mm, h_mm, gray_border=False):
    c.setLineWidth(0.4)
    c.setStrokeColorRGB(0.4, 0.4, 0.4) if gray_border else c.setStrokeColorRGB(0, 0, 0)
    c.rect(x(left_mm), y(top_mm) - h_mm * mm, w_mm * mm, h_mm * mm, fill=0, stroke=1)


def digit_boxes(c, left_mm, top_mm, digits, box_w=8, box_h=10, gap=1.5):
    for i, d in enumerate(digits):
        lx = left_mm + i * (box_w + gap)
        box(c, lx, top_mm, box_w, box_h)
        text(c, lx + box_w / 2, top_mm + box_h / 2 + 1.8, d, size=11, bold=True, center=True)


# ---------- content ----------
# (savollar endi excel_loader.load_questions_from_excel() orqali keladi,
#  bu yerda qattiq yozilgan ro'yxat yo'q)

LETTERS = ["A", "B", "C", "D"]


def shuffle_options(question, rng):
    """Shuffle option order; return (shuffled_texts, letter_map) where
    letter_map tells the checker which shown letter corresponds to which
    ORIGINAL option index -- this is what gets stored per student/exam."""
    order = list(range(4))
    rng.shuffle(order)
    shuffled_texts = [question["variantlar"][i] for i in order]
    # letter_map[shown_letter] = original_option_index
    letter_map = {LETTERS[shown_pos]: orig_idx for shown_pos, orig_idx in enumerate(order)}
    correct_shown_letter = LETTERS[order.index(question["togri_index"])]
    return shuffled_texts, letter_map, correct_shown_letter


def draw_cover(c, student, exam_id, savol_id):
    text(c, 105, 20, "SAFAR TEST", size=8, center=True, gray=True)
    text(c, 105, 30, "SAVOLLAR KITOBCHASI", size=17, bold=True, center=True)
    text(c, 105, 37, f"Imtixon ID: {exam_id}", size=8, center=True, gray=True)

    box(c, 45, 55, 120, 40)
    text(c, 105, 63, "TALABA", size=6.5, bold=True, center=True, gray=True)
    text(c, 105, 72, student["fio"], size=12, bold=True, center=True)
    text(c, 105, 79, f"{student['guruh']} guruh", size=8.5, center=True, gray=True)
    text(c, 105, 89, "Fanlar: " + student["fanlar"], size=7.5, center=True, gray=True)

    text(c, 105, 112, "SAVOL ID (bu raqamni javoblar varag'iga bo'yab belgilang)", size=7, center=True, gray=True)
    digit_w, gap = 10, 2
    total_w = 7 * digit_w + 6 * gap
    digit_boxes(c, 105 - total_w / 2, 118, savol_id, box_w=digit_w, box_h=13, gap=gap)

    box(c, 20, 150, 170, 60, gray_border=True)
    text(c, 25, 158, "KO'RSATMA", size=7.5, bold=True, gray=True)
    lines = [
        "1. Har bir savolga faqat bitta javob belgilang.",
        "2. Javoblarni ushbu kitobchaga emas, alohida javoblar varag'iga bo'yab belgilang.",
        "3. Yuqoridagi 7 xonali savol ID ni javoblar varag'ida ham bo'yab belgilang.",
        "4. Kitobchani boshqa talabaga bermang -- savollar tartibi va variantlar individual.",
        "5. Vaqt tugagach kitobcha va javoblar varag'ini o'qituvchiga topshiring.",
    ]
    ly = 166
    for line in lines:
        text(c, 25, ly, line, size=7.8)
        ly += 8

    text(c, 105, 280, "1-bet", size=7, center=True, gray=True)


def draw_question_page(c, page_questions, page_no, subject_header):
    text(c, 105, 16, subject_header, size=10, bold=True, center=True)
    c.setLineWidth(0.3)
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.line(x(20), y(20), x(190), y(20))

    cur_top = 30
    for q, shown_texts in page_questions:
        text(c, 20, cur_top, f"{q['id']}.", size=9.5, bold=True)
        cur_top = wrapped_text(c, 28, cur_top, q["savol"], max_width_mm=162, size=9.5, bold=True)
        cur_top += 3
        for i, opt_text in enumerate(shown_texts):
            label = f"{LETTERS[i]}) {opt_text}"
            cur_top = wrapped_text(c, 30, cur_top, label, max_width_mm=155, size=9)
            cur_top += 1.5
        cur_top += 9

    text(c, 105, 284, f"{page_no}-bet", size=7, center=True, gray=True)


def build(path, student, exam_id, savol_id, seed, questions):
    rng = random.Random(seed)
    c = canvas.Canvas(path, pagesize=A4)

    draw_cover(c, student, exam_id, savol_id)
    c.showPage()

    answer_key = {}  # savol_id -> {"correct_letter": ..., "letter_map": {...}}
    by_subject = {}
    for q in questions:
        shown_texts, letter_map, correct_letter = shuffle_options(q, rng)
        answer_key[q["id"]] = {
            "fan": q["fan"], "ball": q["ball"],
            "correct_letter_shown_to_student": correct_letter,
            "letter_to_original_option": letter_map,
        }
        by_subject.setdefault(q["fan"], []).append((q, shown_texts))

    page_no = 2
    for subject, qs in by_subject.items():
        draw_question_page(c, qs, page_no, subject)
        c.showPage()
        page_no += 1

    c.save()
    return answer_key


def generate_savol_id(rng, used):
    while True:
        candidate = "".join(str(rng.randint(0, 9)) for _ in range(7))
        if candidate not in used:
            used.add(candidate)
            return candidate


if __name__ == "__main__":
    import os
    import zipfile
    from app.omr.excel_loader import load_questions_from_excel, TemplateError

    EXCEL_PATH = "savollar_shabloni.xlsx"
    EXAM_ID = "EX-2026-0417"
    OUT_DIR = "/output"
    os.makedirs(OUT_DIR, exist_ok=True)

    try:
        questions, warnings = load_questions_from_excel(EXCEL_PATH)
    except TemplateError as e:
        raise SystemExit(f"Shablonda xato: {e}")

    for w in warnings:
        print("OGOHLANTIRISH:", w)
    print(f"{len(questions)} ta savol o'qildi: {EXCEL_PATH}")

    # -- demo guruh: haqiqiy loyihada bu Guruhlarim sahifasidan keladi --
    demo_group = [
        {"fio": "Karimova Nilufar Botir qizi", "guruh": "10-A"},
        {"fio": "Yusupov Sardor Aziz o'g'li", "guruh": "10-A"},
        {"fio": "Rashidova Madina Islom qizi", "guruh": "10-A"},
    ]
    fanlar_str = ", ".join(sorted({q["fan"] for q in questions}))

    id_rng = random.Random(f"{EXAM_ID}-ids")
    used_ids = set()

    exam_answer_key = {"exam_id": EXAM_ID, "talabalar": {}}
    pdf_paths = []

    for student in demo_group:
        savol_id = generate_savol_id(id_rng, used_ids)
        student_full = {**student, "fanlar": fanlar_str}
        pdf_path = os.path.join(OUT_DIR, f"{savol_id}.pdf")

        # har bir talaba uchun seed savol_id'dan olinadi -- shuning uchun
        # keyinchalik xohlagan payt xuddi shu aralashtirishni qayta hosil qilish mumkin
        answer_key = build(
            pdf_path, student_full, exam_id=EXAM_ID,
            savol_id=savol_id, seed=f"{EXAM_ID}-{savol_id}", questions=questions,
        )
        exam_answer_key["talabalar"][savol_id] = {
            "fio": student["fio"], "guruh": student["guruh"], "javoblar": answer_key,
        }
        pdf_paths.append(pdf_path)
        print(f"tayyor: {student['fio']} -> savol_id={savol_id} -> {pdf_path}")

    key_path = os.path.join(OUT_DIR, "javob_kaliti.json")
    with open(key_path, "w", encoding="utf-8") as f:
        json.dump(exam_answer_key, f, ensure_ascii=False, indent=2)

    zip_path = "savollar_kitoblari.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in pdf_paths:
            zf.write(p, arcname=f"savollar/{os.path.basename(p)}")
        zf.write(key_path, arcname="javob_kaliti.json")

    print(f"\nZip tayyor: {zip_path}")
