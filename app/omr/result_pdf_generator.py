# -*- coding: utf-8 -*-
"""
Natija PDF generatori (TZ 19-bo'lim: "NATIJA PDF") -- QAYTA ISHLANGAN DIZAYN.

YANGILANISHLAR:
  1. BUG TUZATILDI: rang-band (ko'k/yashil/sariq/kulrang) endi MUTLAQ
     ball emas, balki FOIZ (total_score / total_possible_score) asosida
     tanlanadi. Eski kod faqat 90-savolli (max ~189 ball) DTM formatiga
     mo'ljallangan edi -- 30 yoki 60 savolli imtihonlarda natija DOIM
     kulrang chiqardi, hatto 100% to'g'ri bo'lsa ham. Yangi chegaralar
     O'zbekiston grant/kontrakt qabul mantig'iga mos: <30% kulrang,
     30-54% sariq, 55-89% yashil, 90%+ ko'k (pastga qarang).
  2. Statistika endi IXCHAM bitta qatorda (rangli, lekin kichik matn) --
     avvalgi versiyada katta (17pt) raqamlar bo'lgan, bu rasmiy hujjat
     uchun ortiqcha "chaqiruvchi"/jiddiyliksiz ko'rinardi.
  3. Info kartada endi so'z-yorliq ("A'LO"/"QONIQARLI" va h.k.)
     CHIZILMAYDI -- faqat foiz raqami va karta foni (rang) orqali
     ifodalanadi.
  4. Joylashuv: chap tomon (skanerlangan javob varag'i rasmi) KENGROQ,
     o'ng tomon (3 ustunli savol-javob ro'yxati) TORROQ qilindi.
  5. "Fanlar bo'yicha natija" endi haqiqiy jadval -- har bir fan/guruh
     uchun to'g'ri/jami, foiz, ball va progress-bar bilan (avval faqat
     "Fan: 8/10" matn qatorlari edi).
  6. Pastdagi TAKRORLANGAN "UMUMIY BALL: ..." yozuvi olib tashlandi
     (yuqorida allaqachon ko'rsatiladi) -- o'rniga ixcham footer
     (tekshirilgan sana + tasdiqlash izohi).
  7. QR ostida qisqa izoh qo'shildi.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional

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
FAINT_GRAY = colors.Color(0.95, 0.95, 0.95)

BAND_BLUE = colors.Color(0.85, 0.92, 1.0)
BAND_GREEN = colors.Color(0.87, 0.96, 0.87)
BAND_YELLOW = colors.Color(1.0, 0.97, 0.82)
BAND_GRAY = colors.Color(0.93, 0.93, 0.93)

ACCENT_BLUE = colors.Color(0.16, 0.40, 0.80)
CORRECT_COLOR = colors.Color(0.13, 0.55, 0.13)
INCORRECT_COLOR = colors.Color(0.75, 0.10, 0.10)
BLANK_COLOR = MEDIUM_GRAY
AMBIGUOUS_COLOR = colors.Color(0.85, 0.55, 0.0)

QUESTION_GROUPS = [(1, 30), (31, 60), (61, 90)]

# ------------------------------------------------------------------
# GRADE/BAND: FOIZ (percentage) asosida -- o'zbekistondagi
# grant/kontrakt qabul mantig'iga moslashtirilgan (TAXMIN -- aniq
# foiz chegaralarini xohlagan payt o'zgartirishingiz mumkin):
#
#   0-29%  -- KULRANG -- o'tish balini yig'olmagan
#   30-54% -- SARIQ    -- o'tish balidan yuqori, lekin past natija
#   55-89% -- YASHIL   -- kontraktga ishonchli kiradi
#   90-100%-- KO'K     -- yuqori natija (grant ehtimoli baland)
#
# MUHIM: endi MUTLAQ ball emas, FOIZ (total_score/total_possible)
# asosida -- shuning uchun imtihon 30/60/90 savoldan iborat bo'lishidan
# qat'i nazar to'g'ri ishlaydi (eski koddagi bug tuzatildi).
# ------------------------------------------------------------------
GRADE_BAND_YELLOW_MIN = 30.0
GRADE_BAND_GREEN_MIN = 55.0
GRADE_BAND_BLUE_MIN = 90.0

GRADE_BANDS = [
    (GRADE_BAND_BLUE_MIN, BAND_BLUE),
    (GRADE_BAND_GREEN_MIN, BAND_GREEN),
    (GRADE_BAND_YELLOW_MIN, BAND_YELLOW),
    (0.0, BAND_GRAY),
]


def _grade_band(percentage: float):
    for threshold, color in GRADE_BANDS:
        if percentage >= threshold:
            return color
    return BAND_GRAY


_SYMBOL_FONT = "Helvetica-Bold"
_SYMBOLS = {"correct": "V", "incorrect": "X"}

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
            _SYMBOLS = {"correct": "\u2713", "incorrect": "\u2715"}
            break
        except Exception:
            pass


def _status_symbol(status: str) -> str:
    return _SYMBOLS["correct"] if status == "correct" else _SYMBOLS["incorrect"]


def _status_color(status: str):
    return CORRECT_COLOR if status == "correct" else INCORRECT_COLOR


def _x(mm_value: float) -> float:
    return mm_value * mm


def _y(top_mm: float) -> float:
    return PAGE_H - top_mm * mm


def _text(c, left_mm, top_mm, value, size=9, bold=False, center=False, right=False, color=BLACK, font=None):
    font_name = font or ("Helvetica-Bold" if bold else "Helvetica")
    c.setFont(font_name, size)
    c.setFillColor(color)
    if center:
        c.drawCentredString(_x(left_mm), _y(top_mm), value)
    elif right:
        c.drawRightString(_x(left_mm), _y(top_mm), value)
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


def _progress_bar(c, left_mm, top_mm, w_mm, h_mm, fraction, color):
    """0..1 oraliqdagi progress-bar -- fon och kulrang, to'ldirilgan
    qismi berilgan rangda, ikkalasi ham yumaloqlangan burchak bilan."""
    fraction = max(0.0, min(1.0, fraction))
    _rounded_box(c, left_mm, top_mm, w_mm, h_mm, FAINT_GRAY, radius_mm=h_mm / 2)
    fill_w = max(w_mm * fraction, h_mm) if fraction > 0 else 0
    if fill_w > 0:
        _rounded_box(c, left_mm, top_mm, min(fill_w, w_mm), h_mm, color, radius_mm=h_mm / 2)


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
    brand_name: str = "ME'ROJ",
    variant_label: Optional[str] = None,
    # YANGI (ixtiyoriy) -- chaqiruvchida allaqachon hisoblangan bo'lsa,
    # qayta hisoblash shart emas (omr_service.py dan uzatiladi). Berilmasa,
    # bu funksiyaning o'zi raw_answers/answer_key'dan hisoblab oladi --
    # eski chaqiruvchilar (parametrsiz) buzilmaydi.
    correct_count: Optional[int] = None,
    incorrect_count: Optional[int] = None,
    blank_count: Optional[int] = None,
    ambiguous_count: Optional[int] = None,
    checked_at: Optional[datetime] = None,
) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # ---- Statistikani hisoblash (agar berilmagan bo'lsa) ----
    if None in (correct_count, incorrect_count, blank_count, ambiguous_count):
        correct_count = incorrect_count = blank_count = ambiguous_count = 0
        for key, meta in answer_key.items():
            given = raw_answers.get(key)
            correct_letter = meta.get("correct_letter_shown_to_student")
            if given is None:
                blank_count += 1
            elif given == "MULTI":
                ambiguous_count += 1
            elif given == correct_letter:
                correct_count += 1
            else:
                incorrect_count += 1

    total_possible = sum(float(meta.get("ball", 1)) for meta in answer_key.values()) or 1.0
    percentage = max(0.0, min(100.0, total_score / total_possible * 100))
    band_color = _grade_band(percentage)

    c = canvas.Canvas(str(output), pagesize=A4)

    # ---------------- Header ----------------
    _text(c, 11, 14, brand_name.upper(), size=9, bold=True, color=MEDIUM_GRAY)
    _text(c, 199, 14, f"Imtihon: {exam_code}", size=8, right=True, color=MEDIUM_GRAY)
    _line(c, 11, 18, 199, 18, width=0.4, color=MEDIUM_GRAY)

    # ---------------- Info karta (rang -- endi FOIZ bo'yicha) ----------------
    info_left, info_top, info_w, info_h = 11, 24, 148, 26
    _rounded_box(c, info_left, info_top, info_w, info_h, band_color)

    _text(c, info_left + 6, info_top + 9, student_full_name.upper(), size=13, bold=True)
    sub_line = f"Guruh: {group_name}    |    {exam_name}"
    if variant_label:
        sub_line += f"    |    Variant: {variant_label}"
    _text(c, info_left + 6, info_top + 15, sub_line, size=8, color=MEDIUM_GRAY)

    # YANGI: alohida so'z-yorliq ("A'LO"/"QONIQARLI" va h.k.) endi
    # CHIZILMAYDI -- faqat karta foni (band_color) va foiz raqami orqali
    # ifodalanadi, bu ko'proq jiddiy/rasmiy ko'rinish beradi.
    _text(c, info_left + 6, info_top + 23, f"{total_score:g} / {total_possible:g} ball  ({percentage:.0f}%)",
          size=11, bold=True)

    # ---------------- QR (signed havola) ----------------
    qr_left, qr_top, qr_size = 163, 24, 22
    if download_url:
        try:
            qr_img = _qr_image_reader(download_url)
            c.drawImage(qr_img, _x(qr_left), _y(qr_top) - qr_size * mm,
                        width=qr_size * mm, height=qr_size * mm,
                        preserveAspectRatio=True, mask="auto")
            _text(c, qr_left + qr_size / 2, qr_top + qr_size + 4, "Natijani onlayn ko'rish",
                  size=5.8, center=True, color=MEDIUM_GRAY)
        except Exception:  # noqa: BLE001
            pass

    # ---------------- Statistika -- ixcham, bitta qator (YANGI) ----------------
    # Avvalgi versiyada bu yerda katta (17pt) raqamlar bo'lgan -- rasmiy
    # hujjat uchun ortiqcha "chaqiruvchi" ko'rinardi. Endi bitta ingichka
    # qatorda, rangi bilan farqlangan, lekin o'lchami kichik va jiddiy.
    stats_top = 57
    stat_items = [
        ("To'g'ri", correct_count, CORRECT_COLOR),
        ("Xato", incorrect_count, INCORRECT_COLOR),
        ("Bo'sh", blank_count, MEDIUM_GRAY),
        ("Noaniq", ambiguous_count, AMBIGUOUS_COLOR),
    ]
    stat_x_positions = [11, 62, 113, 154]
    for (label, value, color), xpos in zip(stat_items, stat_x_positions):
        _text(c, xpos, stats_top, f"{label}: {value}", size=8, bold=True, color=color)
    _line(c, 11, stats_top + 4, 199, stats_top + 4, width=0.4, color=MEDIUM_GRAY)

    # ---------------- Skan rasm (chap, KENGROQ) + javoblar (o'ng, TORROQ) ----------------
    # YANGI: chap tomon (javob titul/skan rasm) kengroq, o'ng tomon
    # (3 ustunli savol-javob ro'yxati) torroq qilindi.
    content_top = 65
    left_w = 125
    right_left = 11 + left_w + 6
    right_w = 199 - right_left
    box_h = 170

    _box(c, 11, content_top, left_w, box_h)
    if scanned_image_path and Path(scanned_image_path).exists():
        try:
            img = ImageReader(scanned_image_path)
            iw, ih = img.getSize()
            box_w_pt, box_h_pt = (left_w - 4) * mm, (box_h - 4) * mm
            scale = min(box_w_pt / iw, box_h_pt / ih)
            draw_w, draw_h = iw * scale, ih * scale
            offset_x = (box_w_pt - draw_w) / 2
            offset_y = (box_h_pt - draw_h) / 2
            c.drawImage(img, _x(11 + 2) + offset_x,
                        _y(content_top) - 2 * mm - offset_y - draw_h,
                        width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001
            _text(c, 11 + left_w / 2, content_top + box_h / 2, "Rasm mavjud emas",
                  center=True, color=MEDIUM_GRAY)
    else:
        _text(c, 11 + left_w / 2, content_top + box_h / 2, "Skanerlangan rasm mavjud emas",
              center=True, color=MEDIUM_GRAY)

    _draw_answer_columns(
        c, right_left, content_top, right_w, box_h,
        total_questions=total_questions, raw_answers=raw_answers, answer_key=answer_key,
    )

    # ---------------- Fanlar bo'yicha natija -- endi jadval (YANGI) ----------------
    subj_top = content_top + box_h + 8
    _text(c, 11, subj_top, "FANLAR BO'YICHA NATIJA", size=8.5, bold=True, color=MEDIUM_GRAY)

    header_y = subj_top + 6
    col_fan_x, col_frac_x, col_pct_x, col_ball_x, bar_left, bar_w = 11, 78, 100, 118, 138, 61
    _text(c, col_fan_x, header_y, "Fan", size=6.8, color=MEDIUM_GRAY)
    _text(c, col_frac_x, header_y, "To'g'ri", size=6.8, color=MEDIUM_GRAY)
    _text(c, col_pct_x, header_y, "Foiz", size=6.8, color=MEDIUM_GRAY)
    _text(c, col_ball_x, header_y, "Ball", size=6.8, color=MEDIUM_GRAY)

    available_h = 270 - (header_y + 3)
    n_rows = max(len(per_subject), 1)
    row_h = min(7.0, max(4.2, available_h / n_rows))
    font_size = 8.3 if row_h >= 5.5 else 6.8

    row_y = header_y + row_h
    for fan, s in per_subject.items():
        pct = (s["correct"] / s["total"] * 100) if s["total"] else 0.0
        bar_fill_color = ACCENT_BLUE if pct >= 45 else colors.Color(0.75, 0.35, 0.35)

        _text(c, col_fan_x, row_y, fan, size=font_size)
        _text(c, col_frac_x, row_y, f"{s['correct']}/{s['total']}", size=font_size)
        _text(c, col_pct_x, row_y, f"{pct:.0f}%", size=font_size)
        _text(c, col_ball_x, row_y, f"{s.get('score', 0):g}", size=font_size)
        _progress_bar(c, bar_left, row_y - 2.6, bar_w, 3.0, s["correct"] / s["total"] if s["total"] else 0,
                      bar_fill_color)
        row_y += row_h

    # ---------------- Ixcham footer (takrorlangan "UMUMIY BALL" OLIB TASHLANDI) ----------------
    footer_top = 280
    _line(c, 11, footer_top - 4, 199, footer_top - 4, width=0.4, color=MEDIUM_GRAY)
    checked_str = (checked_at or datetime.now()).strftime("%d.%m.%Y %H:%M")
    _text(c, 11, footer_top, f"Tekshirilgan sana: {checked_str}", size=6.8, color=MEDIUM_GRAY)
    _text(c, 199, footer_top, "Bu hujjat avtomatik generatsiya qilingan.", size=6.8, right=True, color=MEDIUM_GRAY)

    c.showPage()
    c.save()
    return str(output)


def _draw_answer_columns(c, left_mm, top_mm, w_mm, h_mm, total_questions, raw_answers, answer_key):
    _box(c, left_mm, top_mm, w_mm, h_mm)

    active_groups = [(s, e) for (s, e) in QUESTION_GROUPS if s <= total_questions]
    if not active_groups:
        active_groups = [QUESTION_GROUPS[0]]

    col_count = len(active_groups)
    col_w = w_mm / col_count
    max_rows = max(end - start + 1 for start, end in active_groups)
    # YANGI: ustun torroq bo'lgani uchun padding/font biroz kichraytirildi,
    # shu bilan 3 ustun ham matn kesilmasdan sig'adi.
    pad = 1.4
    row_h = min(5.1, max(3.6, (h_mm - pad - 3) / max_rows))
    font_size = 6.9 if row_h >= 4.6 else 6.0

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
            # YANGI: "1." o'rniga "1" -- torroq ustunda joy tejash uchun
            label = f"{q}" if shown == "" else f"{q} {shown}"
            _text(c, col_left + pad, row_top, label, size=font_size)
            _text(c, col_left + col_w - pad - 2.6, row_top, _status_symbol(status),
                  size=font_size, bold=True, color=_status_color(status), font=_SYMBOL_FONT)

        if col_idx < col_count - 1:
            _line(c, col_left + col_w, top_mm + 1, col_left + col_w, top_mm + h_mm - 1)
