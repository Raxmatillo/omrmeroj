# -*- coding: utf-8 -*-
"""
Natija PDF generatori (TZ 19-bo'lim: "NATIJA PDF").

Ko'rinishi (foydalanuvchi yuborgan namunaga mos):

    +----------------------------------------------------------+
    | BRAND_NAME                                                |
    |  +------------------------------------------+   [QR]      |
    |  |  O'QUVCHINING TO'LIQ ISM-FAMILIYASI       |             |
    |  |  Guruh: ...           Umumiy bali: 111.20 |             |
    |  +------------------------------------------+ (rang -     |
    |                                                ball bo'yicha)
    |  +----------------------+   +-------------------------+   |
    |  | Skanerlangan javob   |   |  1.  ---     31. A ✕     |   |
    |  | varag'i (rasm)       |   |  2.  B  ✓    32. C ✕     |   |
    |  |                      |   |  ...                     |   |
    |  +----------------------+   +-------------------------+   |
    |  Fanlar bo'yicha: Tarix 21/30, Matematika 18/30 ...        |
    |                      UMUMIY BALL: 111.20                  |
    +----------------------------------------------------------+

MUHIM (rang chegaralari, TZ 19-bo'lim so'zma-so'z):
    150+          -> och moviy
    120 - 149.99  -> och yashil
    90  - 119.99  -> och sariq
    0   - 89.99   -> kulrang

    Bu qiymatlar MUTLAQ ball asosida (foiz emas). Agar imtihonning
    maksimal bali (masalan 30 savol x 1.1 ball = 33) shu chegaralardan
    ancha past bo'lsa, natija deyarli har doim "kulrang" chiqadi -- bu
    TZ'dagi aniq sonlarni o'zgartirmasdan qo'llashning tabiiy natijasi.
    Agar buning o'rniga foiz (percentage) asosida rang tanlash kerak
    bo'lsa, faqat `_score_band_color()` funksiyasini o'zgartirish
    kifoya.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = A4

BLACK = colors.black
WHITE = colors.white
MEDIUM_GRAY = colors.Color(0.45, 0.45, 0.45)
LIGHT_GRAY = colors.Color(0.90, 0.90, 0.90)

# TZ 19-bo'limdagi rang sxemasi
BAND_BLUE = colors.Color(0.85, 0.92, 1.0)     # och moviy   -- 150+
BAND_GREEN = colors.Color(0.87, 0.96, 0.87)   # och yashil  -- 120-149.99
BAND_YELLOW = colors.Color(1.0, 0.97, 0.82)   # och sariq   -- 90-119.99
BAND_GRAY = colors.Color(0.93, 0.93, 0.93)    # kulrang     -- 0-89.99

CORRECT_COLOR = colors.Color(0.13, 0.55, 0.13)
INCORRECT_COLOR = colors.Color(0.75, 0.10, 0.10)
BLANK_COLOR = MEDIUM_GRAY
AMBIGUOUS_COLOR = colors.Color(0.85, 0.55, 0.0)

QUESTION_GROUPS = [(1, 30), (31, 60), (61, 90)]

# ------------------------------------------------------------------
# Unicode belgilar (✓ ✕ ⚠) uchun DejaVu Sans -- Helvetica (base14,
# WinAnsi) bu belgilarni ishonchli chizolmaydi. Loyihada WeasyPrint
# uchun allaqachon "DejaVu Sans" ishlatilgan (booklet_html_generator.py),
# demak server muhitida bu shrift mavjud. Topilmasa -- ASCII fallback
# ("V"/"X"/"-"/"!"), dastur hech qachon buzilmaydi.
# ------------------------------------------------------------------

_SYMBOL_FONT = "Helvetica-Bold"
_SYMBOLS = {"correct": "V", "incorrect": "X", "blank": "-", "ambiguous": "!"}

_DEJAVU_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]

for _path in _DEJAVU_CANDIDATES:
    if Path(_path).exists():
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", _path))
            _SYMBOL_FONT = "DejaVuSans-Bold"
            _SYMBOLS = {"correct": "\u2713", "incorrect": "\u2715", "blank": "\u2014", "ambiguous": "\u26A0"}
            break
        except Exception:  # noqa: BLE001 -- shrift yuklanmasa, ASCII fallback bilan davom etamiz
            pass


def _status_symbol(status: str) -> str:
    return _SYMBOLS.get(status, "?")


def _status_color(status: str):
    return {
        "correct": CORRECT_COLOR,
        "incorrect": INCORRECT_COLOR,
        "blank": BLANK_COLOR,
        "ambiguous": AMBIGUOUS_COLOR,
    }.get(status, BLACK)


def _score_band_color(total_score: float):
    if total_score >= 150:
        return BAND_BLUE
    if total_score >= 120:
        return BAND_GREEN
    if total_score >= 90:
        return BAND_YELLOW
    return BAND_GRAY


# ------------------------------------------------------------------
# Koordinata / chizish yordamchilari (boshqa app/omr/*.py modullari
# bilan bir xil uslub -- top-left origin, mm birligi)
# ------------------------------------------------------------------

def _x(mm_value: float) -> float:
    return mm_value * mm


def _y(top_mm: float) -> float:
    return PAGE_H - top_mm * mm


def _text(c, left_mm, top_mm, value, size=9, bold=False, center=False, color=BLACK, font=None):
    font_name = font or ("Helvetica-Bold" if bold else "Helvetica")
    c.setFont(font_name, size)
    c.setFillColor(color)
    if center:
        c.drawCentredString(_x(left_mm), _y(top_mm), value)
    else:
        c.drawString(_x(left_mm), _y(top_mm), value)


def _rounded_box(c, left_mm, top_mm, w_mm, h_mm, fill_color, radius_mm=3.0, stroke_color=None):
    c.setFillColor(fill_color)
    if stroke_color:
        c.setStrokeColor(stroke_color)
        stroke = 1
    else:
        stroke = 0
    c.roundRect(_x(left_mm), _y(top_mm) - h_mm * mm, w_mm * mm, h_mm * mm, radius_mm * mm,
                fill=1, stroke=stroke)


def _box(c, left_mm, top_mm, w_mm, h_mm, line_width=0.4, gray=True):
    c.setLineWidth(line_width)
    c.setStrokeColor(MEDIUM_GRAY if gray else BLACK)
    c.setFillColor(WHITE)
    c.rect(_x(left_mm), _y(top_mm) - h_mm * mm, w_mm * mm, h_mm * mm, fill=0, stroke=1)


def _line(c, x1, top1, x2, top2, width=0.3, color=LIGHT_GRAY):
    c.setLineWidth(width)
    c.setStrokeColor(color)
    c.line(_x(x1), _y(top1), _x(x2), _y(top2))


# ------------------------------------------------------------------
# QR (signed download havolasi)
# ------------------------------------------------------------------

def _qr_image_reader(data: str) -> ImageReader:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                        box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


# ------------------------------------------------------------------
# Asosiy generator
# ------------------------------------------------------------------

def generate_result_pdf(
    output_path: str,
    student_full_name: str,
    group_name: str,
    exam_name: str,
    exam_code: str,
    total_score: float,
    total_questions: int,
    raw_answers: Dict[str, Optional[str]],
    answer_key: dict,
    per_subject: Dict[str, dict],
    scanned_image_path: Optional[str] = None,
    download_url: Optional[str] = None,
    brand_name: str = "BRAND NAME",
) -> str:
    """
    raw_answers  -- {str(tartib): "A"|None|"MULTI"} (omr_service.py
                    natijasi bilan bir xil format).
    answer_key   -- ExamStudent.answer_key_json format:
                    {str(tartib): {"correct_letter_shown_to_student",
                                   "fan", "ball", ...}}
    per_subject  -- {fan: {"correct": int, "total": int}}
    """

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(output), pagesize=A4)

    # ---------------- Header ----------------
    _text(c, 11, 14, brand_name.upper(), size=9, bold=True, color=MEDIUM_GRAY)
    c.setFont("Helvetica", 8)
    c.setFillColor(MEDIUM_GRAY)
    c.drawRightString(_x(199), _y(14), f"Imtihon: {exam_code}")
    _line(c, 11, 18, 199, 18, width=0.4, color=MEDIUM_GRAY)

    # ---------------- O'quvchi bloki (rang ball bo'yicha) ----------------
    band_color = _score_band_color(total_score)
    info_left, info_top, info_w, info_h = 11, 24, 148, 26
    _rounded_box(c, info_left, info_top, info_w, info_h, band_color)

    _text(c, info_left + info_w / 2, info_top + 11, student_full_name.upper(),
          size=13, bold=True, center=True)
    sub_line = f"Guruh: {group_name}    |    {exam_name}"
    _text(c, info_left + info_w / 2, info_top + 18, sub_line, size=8.5,
          center=True, color=MEDIUM_GRAY)
    _text(c, info_left + info_w / 2, info_top + 23.5, f"Umumiy bali: {total_score:g}",
          size=11, bold=True, center=True)

    # ---------------- QR (signed havola) ----------------
    qr_left, qr_top, qr_size = 163, 24, 26
    if download_url:
        try:
            qr_img = _qr_image_reader(download_url)
            c.drawImage(qr_img, _x(qr_left), _y(qr_top) - qr_size * mm,
                        width=qr_size * mm, height=qr_size * mm,
                        preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001 -- QR yasab bo'lmasa, PDF baribir yaratiladi
            pass

    # ---------------- Chap: skanerlangan varaq / O'ng: 3 ustun natija ----------------
    content_top = 56
    left_w = 78
    right_left = 11 + left_w + 6
    right_w = 199 - right_left

    _box(c, 11, content_top, left_w, 175)
    if scanned_image_path and Path(scanned_image_path).exists():
        try:
            img = ImageReader(scanned_image_path)
            iw, ih = img.getSize()
            # A4 rasm proporsiyasiga moslab, box ichiga sig'diramiz
            box_w_pt, box_h_pt = (left_w - 4) * mm, (175 - 4) * mm
            scale = min(box_w_pt / iw, box_h_pt / ih)
            draw_w, draw_h = iw * scale, ih * scale
            offset_x = (box_w_pt - draw_w) / 2
            c.drawImage(img, _x(11 + 2) + offset_x, _y(content_top) - 2 * mm - draw_h,
                        width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001
            _text(c, 11 + left_w / 2, content_top + 85, "Rasm mavjud emas", center=True,
                  color=MEDIUM_GRAY)
    else:
        _text(c, 11 + left_w / 2, content_top + 85, "Skanerlangan rasm mavjud emas",
              center=True, color=MEDIUM_GRAY)

    _draw_answer_columns(
        c, right_left, content_top, right_w, 175,
        total_questions=total_questions, raw_answers=raw_answers, answer_key=answer_key,
    )

    # ---------------- Fanlar bo'yicha natija ----------------
    subj_top = content_top + 179
    _text(c, 11, subj_top, "FANLAR BO'YICHA NATIJA", size=8.5, bold=True, color=MEDIUM_GRAY)
    line_y = subj_top + 6
    for fan, s in per_subject.items():
        _text(c, 11, line_y, f"{fan}: {s['correct']}/{s['total']}", size=9)
        line_y += 5.5

    # ---------------- Umumiy ball (pastda, katta) ----------------
    footer_top = 275
    _line(c, 11, footer_top - 6, 199, footer_top - 6, width=0.5, color=MEDIUM_GRAY)
    _text(c, 105, footer_top, f"UMUMIY BALL: {total_score:g}", size=15, bold=True, center=True)

    c.showPage()
    c.save()
    return str(output)


def _draw_answer_columns(c, left_mm, top_mm, w_mm, h_mm, total_questions, raw_answers, answer_key):
    """O'ng tomondagi 3 ustunli (1-30 / 31-60 / 61-90) natija ro'yxati,
    faqat total_questions doirasidagi ustunlar chiziladi (universal 90
    savollik shablon -- TZ 8-bo'lim)."""

    _box(c, left_mm, top_mm, w_mm, h_mm)

    active_groups = [(s, e) for (s, e) in QUESTION_GROUPS if s <= total_questions]
    if not active_groups:
        active_groups = [QUESTION_GROUPS[0]]

    col_count = len(active_groups)
    col_w = w_mm / col_count
    row_h = 5.4
    pad = 3

    for col_idx, (start, end) in enumerate(active_groups):
        col_left = left_mm + col_idx * col_w
        end = min(end, total_questions)
        cur_top = top_mm + pad + 3
        for q in range(start, end + 1):
            key = str(q)
            meta = answer_key.get(key, {})
            correct_letter = meta.get("correct_letter_shown_to_student")
            given = raw_answers.get(key)

            if given is None:
                status, shown = "blank", ""
            elif given == "MULTI":
                status, shown = "ambiguous", "?"
            elif correct_letter and given == correct_letter:
                status, shown = "correct", given
            else:
                status, shown = "incorrect", given

            row_top = cur_top + (q - start) * row_h
            label = f"{q}." if shown == "" else f"{q}. {shown}"
            _text(c, col_left + pad, row_top, label, size=8.3)
            _text(c, col_left + col_w - pad - 4, row_top, _status_symbol(status),
                  size=8.3, bold=True, color=_status_color(status), font=_SYMBOL_FONT)

        if col_idx < col_count - 1:
            _line(c, col_left + col_w, top_mm + 1, col_left + col_w, top_mm + h_mm - 1)