# -*- coding: utf-8 -*-

"""
OMR Answer Sheet Generator
===========================

A4 OMR javoblar varaqasi generatori.

Xususiyatlar:
- A4 Portrait
- 4 ta OMR registration marker
- Real QR Code
- QR ichida exam_id + booklet_id
- 90 tagacha savol
- 30 / 45 / 60 / 90 savol
- Dinamik fanlar
- Dinamik savol diapazonlari
- A/B/C/D variantlari
- O'quvchi ma'lumotlari
- OMR uchun aniq koordinatalar
- TIMING TRACK: har bir qator uchun kichik "lokator" belgisi -- reader
  bubble y-pozitsiyasini arifmetik formula bilan HISOBLAB TOPISH o'rniga,
  shu belgining haqiqiy (siyohdagi) markazidan o'qiydi. Bu -- telefon
  fotosida perspective-correction xatosi qator raqami oshgan sari
  to'planib (drift qilib) ketishining oldini oladi (real Scantron/DTM
  turidagi tizimlarda ham ishlatiladigan standart texnika).

Production:
Bu modul keyinchalik FastAPI backend ichida ishlatilishi mumkin.

O'rnatish:

    pip install reportlab qrcode[pil] pillow

Ixtiyoriy:
    pip install pymupdf opencv-python numpy
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from io import BytesIO

import qrcode

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


# ============================================================
# PAGE CONFIG
# ============================================================

PAGE_W, PAGE_H = A4

PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297

LEFT_MARGIN_MM = 10
RIGHT_MARGIN_MM = 10

BLACK = colors.black
WHITE = colors.white

LIGHT_GRAY = colors.Color(
    red=0.82,
    green=0.82,
    blue=0.82
)

MEDIUM_GRAY = colors.Color(
    red=0.45,
    green=0.45,
    blue=0.45
)

# ============================================================
# OMR / READER BILAN ULASHTIRILGAN KONSTANTALAR
#
# MUHIM: bu qiymatlar app/omr/omr_reader.py dagi bir xil nomdagi
# konstantalar bilan ANIQ BIR XIL bo'lishi SHART. Bittasini
# o'zgartirsangiz, ikkinchisini ham yangilang -- aks holda reader
# generator chizgan joydan boshqa joyni qidiradi.
# ============================================================

# Registratsiya markeri -- 5mm dan 8mm ga kattalashtirildi: telefon
# kamerasi bilan olingan (past piksel zichlikdagi) fotoda subpixel
# markaz aniqrog'i uchun kattaroq kontur kerak.
REGISTRATION_MARKER_SIZE_MM = 8.0

# Timing track -- ustunning chap chetiga, har bir qatorga mos keladigan
# kichik to'ldirilgan kvadrat. offset -- ustun chap chegarasidan.
TIMING_MARK_OFFSET_MM = 1.6
TIMING_MARK_SIZE_MM = 1.4


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class Student:
    id: str
    first_name: str
    last_name: str
    father_name: str = ""
    group_name: str = ""

    @property
    def full_name(self) -> str:
        parts = [
            self.last_name,
            self.first_name,
            self.father_name
        ]

        return " ".join(
            part.strip()
            for part in parts
            if part and part.strip()
        )


@dataclass
class SubjectBlock:
    """
    Bitta fan bloki.

    Masalan:

    1-30
    Tarix
    1.1 ball
    """

    start: int
    end: int
    subject: str
    point: float

    # True bo'lsa -- bu blok BIR NECHTA turli ball qiymatiga ega
    # savollarni birlashtirgan (masalan bitta ustunda 1.1, 2.1 va 3.1
    # ballli savollar aralash). Bunday holda `point` maydoni faqat
    # BIRINCHI savolning ballini saqlaydi va ustunning boshida "X ball"
    # yozuvini CHIZISH KERAK EMAS -- chunki u chalg'ituvchi/noto'g'ri
    # bo'lar edi (draw_answer_column shu bayroqni tekshiradi).
    mixed_points: bool = False

    @property
    def question_count(self) -> int:
        return self.end - self.start + 1

    @property
    def total_point(self) -> float:
        return self.question_count * self.point


@dataclass
class Exam:
    exam_id: str
    exam_name: str

    # 30, 45, 60 yoki 90
    total_questions: int

    # USTUNLARGA bubble chizish uchun -- har bir ustun (1-30/31-60/61-90)
    # uchun BITTA blok (agar bir ustunda bir nechta fan/ball aralash
    # bo'lsa, ular shu yerda bitta blokka birlashtirilgan bo'lishi
    # mumkin -- app/services/exam_service.py._build_subject_blocks'ga
    # qarang).
    subjects: List[SubjectBlock] = field(
        default_factory=list
    )

    # O'QUVCHI MA'LUMOTLARI qutisidagi "Fan / Oraliq / Soni / Ball / Jami"
    # jadvali uchun -- HAR BIR fan/ball guruhi ALOHIDA qator sifatida.
    # `subjects`dan farqli o'laroq bu yerda birlashtirish YO'Q, shuning
    # uchun 30 ta savol 3 xil fandan iborat bo'lsa ham (masalan Majburiy
    # fanlar 1.1 ball, Matematika 2.1 ball, Ingliz tili 3.1 ball -- har
    # birida 10tadan), jadvalda 3 ta alohida qator ko'rinadi. Bo'sh
    # qoldirilsa (masalan eski chaqiruvlar bilan moslik uchun),
    # draw_student_info() `subjects`ni ishlatadi (fallback).
    subject_breakdown: List[SubjectBlock] = field(
        default_factory=list
    )

    @property
    def _breakdown_or_subjects(self) -> List[SubjectBlock]:
        return self.subject_breakdown or self.subjects

    @property
    def total_possible_score(self) -> float:
        return sum(
            subject.total_point
            for subject in self._breakdown_or_subjects
        )


@dataclass
class Booklet:
    """
    Har bir o'quvchiga individual savollar kitobchasi.

    QR kod aynan shu booklet_id orqali
    o'quvchi va imtihon bilan bog'lanadi.
    """

    booklet_id: str
    exam_id: str
    student_id: str


# ============================================================
# COORDINATE HELPERS
# ============================================================

def x(mm_value: float) -> float:
    """
    Chapdan boshlab millimetrni ReportLab pointga aylantiradi.
    """
    return mm_value * mm


def y(top_mm: float) -> float:
    """
    Yuqoridan boshlab millimetrni ReportLab y koordinatasiga aylantiradi.
    """
    return PAGE_H - top_mm * mm


# ============================================================
# BASIC DRAWING HELPERS
# ============================================================

def set_black(c):
    c.setFillColor(BLACK)
    c.setStrokeColor(BLACK)


def draw_text(
    c,
    left_mm: float,
    top_mm: float,
    value: str,
    size: float = 8,
    bold: bool = False,
    center: bool = False,
    gray: bool = False,
):
    """
    Matn chizish.
    """

    font = "Helvetica-Bold" if bold else "Helvetica"

    c.setFont(font, size)

    if gray:
        c.setFillColor(MEDIUM_GRAY)
    else:
        c.setFillColor(BLACK)

    if center:
        c.drawCentredString(
            x(left_mm),
            y(top_mm),
            value
        )
    else:
        c.drawString(
            x(left_mm),
            y(top_mm),
            value
        )


def draw_box(
    c,
    left_mm: float,
    top_mm: float,
    width_mm: float,
    height_mm: float,
    line_width: float = 0.35,
):
    """
    To'rtburchak box.
    """

    c.setLineWidth(line_width)
    c.setStrokeColor(BLACK)
    c.setFillColor(WHITE)

    c.rect(
        x(left_mm),
        y(top_mm) - height_mm * mm,
        width_mm * mm,
        height_mm * mm,
        fill=0,
        stroke=1
    )


def draw_line(
    c,
    x1_mm: float,
    y1_top_mm: float,
    x2_mm: float,
    y2_top_mm: float,
    width: float = 0.3,
    gray: bool = False,
):
    c.setLineWidth(width)

    if gray:
        c.setStrokeColor(LIGHT_GRAY)
    else:
        c.setStrokeColor(BLACK)

    c.line(
        x(x1_mm),
        y(y1_top_mm),
        x(x2_mm),
        y(y2_top_mm)
    )


def draw_dashed_line(
    c,
    x1_mm: float,
    top_mm: float,
    x2_mm: float,
):
    c.setLineWidth(0.25)
    c.setStrokeColor(MEDIUM_GRAY)
    c.setDash(1, 1.5)

    c.line(
        x(x1_mm),
        y(top_mm),
        x(x2_mm),
        y(top_mm)
    )

    c.setDash()


# ============================================================
# OMR REGISTRATION MARKERS
# ============================================================

def draw_registration_markers(c):
    """
    OpenCV perspective correction uchun 4 ta marker.

    Markerlar:
        top-left
        top-right
        bottom-left
        bottom-right

    Marker o'lchami REGISTRATION_MARKER_SIZE_MM orqali boshqariladi --
    omr_reader.py dagi MARKER_SIZE_MM bilan bir xil bo'lishi shart.
    """

    marker_size = REGISTRATION_MARKER_SIZE_MM

    positions = [
        (7, 7),
        (198, 7),
        (7, 285),
        (198, 285),
    ]

    c.setFillColor(BLACK)

    for left, top in positions:

        c.rect(
            x(left),
            y(top) - marker_size * mm,
            marker_size * mm,
            marker_size * mm,
            fill=1,
            stroke=0
        )


# ============================================================
# TIMING TRACK (QATOR LOKATORI)
# ============================================================

def draw_timing_mark(
    c,
    center_x_mm: float,
    center_y_top_mm: float,
    size_mm: float = TIMING_MARK_SIZE_MM,
):
    """
    Kichik to'ldirilgan kvadrat -- reader bu qatorning HAQIQIY
    y-markazini shu belgidan topadi, arifmetik formuladan emas.

    Har bir ustunda (subject_block bo'sh bo'lsa ham) MAX_ROWS ta
    belgi chiziladi -- shu bilan reader tomonida qator indekslari
    barcha ustunlarda bir xil qoladi.
    """

    c.setFillColor(BLACK)
    c.rect(
        x(center_x_mm - size_mm / 2),
        y(center_y_top_mm) - size_mm * mm / 2,
        size_mm * mm,
        size_mm * mm,
        fill=1,
        stroke=0,
    )


# ============================================================
# OMR BUBBLE
# ============================================================

def draw_bubble(
    c,
    center_x_mm: float,
    center_y_top_mm: float,
    radius_mm: float = 1.8,
):
    """
    Bo'sh OMR bubble.

    Diametri:
        3.6 mm
    """

    c.setLineWidth(0.45)
    c.setStrokeColor(BLACK)
    c.setFillColor(WHITE)

    c.circle(
        x(center_x_mm),
        y(center_y_top_mm),
        radius_mm * mm,
        fill=0,
        stroke=1
    )


def draw_filled_bubble(
    c,
    center_x_mm: float,
    center_y_top_mm: float,
    radius_mm: float = 1.8,
):
    """
    Demo uchun to'ldirilgan bubble.
    """

    c.setFillColor(BLACK)
    c.setStrokeColor(BLACK)

    c.circle(
        x(center_x_mm),
        y(center_y_top_mm),
        radius_mm * mm,
        fill=1,
        stroke=1
    )


# ============================================================
# QR CODE
# ============================================================

def create_qr_image(
    exam_id: str,
    booklet_id: str,
):
    """
    QR kodni PNG bytes ko'rinishida qaytaradi.
    """

    payload = {
        "exam_id": exam_id,
        "booklet_id": booklet_id,
    }

    qr_data = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":")
    )

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )

    qr.add_data(qr_data)
    qr.make(fit=True)

    img = qr.make_image(
        fill_color="black",
        back_color="white"
    )

    # PIL image -> PNG bytes
    buffer = BytesIO()

    img.save(
        buffer,
        format="PNG"
    )

    buffer.seek(0)

    return buffer


def draw_qr(
    c,
    exam_id: str,
    booklet_id: str,
    left_mm: float,
    top_mm: float,
    size_mm: float = 22,
):
    """
    QR kodni PDF ichiga joylashtiradi.
    """

    qr_buffer = create_qr_image(
        exam_id=exam_id,
        booklet_id=booklet_id
    )

    qr_image = ImageReader(
        qr_buffer
    )

    c.drawImage(
        qr_image,
        x(left_mm),
        y(top_mm) - size_mm * mm,
        width=size_mm * mm,
        height=size_mm * mm,
        preserveAspectRatio=True,
        mask="auto"
    )


# ============================================================
# HEADER
# ============================================================

def draw_header(
    c,
    exam: Exam,
    brand_name: str,
):
    draw_text(
        c,
        105,
        12,
        brand_name.upper(),
        size=8,
        bold=True,
        center=True,
        gray=True,
    )

    draw_text(
        c,
        105,
        19,
        "JAVOBLAR VARAQASI",
        size=15,
        bold=True,
        center=True,
    )

    draw_text(
        c,
        105,
        25,
        f"Imtihon ID: {exam.exam_id}",
        size=7.5,
        center=True,
        gray=True,
    )

    draw_text(
        c,
        105,
        30,
        exam.exam_name,
        size=7,
        center=True,
        gray=True,
    )


# ============================================================
# STUDENT INFORMATION
# ============================================================

def draw_student_info(
    c,
    student: Student,
    exam: Exam,
):
    """
    O'quvchi ma'lumotlari + imtihon bo'yicha
    fanlar / savollar soni / ball taqsimoti.

    MUHIM:
        Barcha kontent shu funksiya ichida
        belgilangan (left, top, width, height)
        maydonidan HECH QACHON chiqmasligi kerak.

        Fanlar soni ko'p yoki oz bo'lishidan
        qat'iy nazar, jadval balandligi va shrift
        o'lchami avtomatik moslashtiriladi.
    """

    left = 11
    top = 35

    width = 88
    height = 45

    draw_box(
        c,
        left,
        top,
        width,
        height
    )

    inner_left = left + 3
    inner_right = left + width - 3

    # ------------------------------------------------------
    # Yuqori qism: sarlavha + ism-familiya + guruh
    # (bular doim bir xil balandlikni egallaydi)
    #
    # Bu qism imkon qadar ixcham qilingan, shunda
    # pastdagi jadvalga ko'proq joy (va shu bilan
    # kattaroq shrift) qoladi.
    # ------------------------------------------------------

    cursor_top = top + 4

    draw_text(
        c,
        inner_left,
        cursor_top,
        "ABITURIYENT / O'QUVCHI MA'LUMOTLARI",
        size=6.3,
        bold=True,
        gray=True,
    )

    cursor_top += 5

    draw_text(
        c,
        inner_left,
        cursor_top,
        f"Ism-familiya: {student.full_name}",
        size=8,
        bold=True,
    )

    cursor_top += 4.3

    draw_text(
        c,
        inner_left,
        cursor_top,
        f"Guruh: {student.group_name}",
        size=6.5,
        gray=True,
    )

    cursor_top += 3.2

    # Yuqori va pastki blok orasidagi ajratuvchi chiziq
    draw_line(
        c,
        inner_left,
        cursor_top,
        inner_right,
        cursor_top,
        width=0.25,
        gray=True,
    )

    cursor_top += 2.2

    # ------------------------------------------------------
    # Pastki qism: fanlar / savollar soni / ball jadvali
    #
    # Bu qism DINAMIK: nechta fan bo'lsa ham
    # (1, 2 yoki 3 ta), qolgan bo'sh joy ichiga
    # avtomatik sig'diriladi -- shrift esa mavjud
    # joyga qarab imkon boricha KATTA qilinadi.
    # ------------------------------------------------------

    # MUHIM: bu yerda `exam.subjects` (ustunlarga bubble chizish uchun
    # birlashtirilgan bloklar) EMAS, `exam.subject_breakdown` (har fan/ball
    # guruhi alohida qator) ishlatiladi -- aks holda 30 talik testda 3 xil
    # fan bitta blokka birlashtirilgani uchun jadvalda faqat 1 ta qator
    # (va faqat birinchi fanning balli) chiqib qolar edi.
    subjects = exam._breakdown_or_subjects

    table_top = cursor_top
    table_bottom = top + height - 2
    available_height = table_bottom - table_top

    # Jadval qatorlari: 1 ta sarlavha qatori
    # + har bir fan uchun 1 qator
    # + 1 ta "JAMI" qatori
    total_rows = len(subjects) + 2

    if total_rows <= 0 or available_height <= 0:
        return

    row_h = available_height / total_rows

    # Qator balandligiga qarab shrift o'lchamini
    # hisoblaymiz: joy ko'p bo'lsa -- shrift yiriklashadi,
    # joy kam bo'lsa (fanlar ko'p bo'lsa) -- kichraydi.
    # Yuqori chegara o'qish uchun qulay va ustunlarga
    # sig'adigan darajada tanlangan.
    font_size = max(6.0, min(8.5, row_h * 1.55))
    header_font_size = max(5.2, min(7.0, font_size - 1.3))

    # Ustunlar (mm, inner_left dan nisbiy emas -- absolyut x)
    col_subject_x = inner_left
    col_range_x = inner_left + 33
    col_count_x = inner_left + 49
    col_point_x = inner_left + 61
    col_total_x = inner_left + 71

    def draw_row(row_index, cells, bold=False, size=font_size, gray_row=False):
        row_y = table_top + row_h * (row_index + 1) - (row_h - font_size) / 2 - 0.5

        for text_value, cx in cells:
            draw_text(
                c,
                cx,
                row_y,
                text_value,
                size=size,
                bold=bold,
                gray=gray_row,
            )

    # Sarlavha qatori
    draw_row(
        0,
        [
            ("Fan", col_subject_x),
            ("Oraliq", col_range_x),
            ("Soni", col_count_x),
            ("Ball", col_point_x),
            ("Jami", col_total_x),
        ],
        bold=True,
        size=header_font_size,
        gray_row=True,
    )

    # Fan qatorlari
    for i, subject in enumerate(subjects):

        subject_name = subject.subject

        # Nomi juda uzun bo'lsa, joy yetmay
        # qolmasligi uchun qisqartiramiz.
        max_chars = 12
        if len(subject_name) > max_chars:
            subject_name = subject_name[: max_chars - 1] + "."

        draw_row(
            i + 1,
            [
                (subject_name, col_subject_x),
                (f"{subject.start}-{subject.end}", col_range_x),
                (str(subject.question_count), col_count_x),
                (f"{subject.point:g}", col_point_x),
                (f"{subject.total_point:g}", col_total_x),
            ],
        )

    # JAMI (umumiy) qatori
    total_questions = sum(s.question_count for s in subjects)
    total_score = exam.total_possible_score

    draw_row(
        len(subjects) + 1,
        [
            ("JAMI", col_subject_x),
            ("", col_range_x),
            (str(total_questions), col_count_x),
            ("", col_point_x),
            (f"{total_score:g}", col_total_x),
        ],
        bold=True,
    )

    # Jadval ustidan ingichka ajratuvchi chiziq (sarlavha ostida)
    header_bottom = table_top + row_h
    draw_line(
        c,
        inner_left,
        header_bottom,
        inner_right,
        header_bottom,
        width=0.2,
        gray=True,
    )


# ============================================================
# QR INFORMATION BOX
# ============================================================

def draw_qr_box(
    c,
    exam: Exam,
    booklet: Booklet,
):
    left = 103
    top = 35

    width = 96
    height = 45

    draw_box(
        c,
        left,
        top,
        width,
        height
    )

    draw_text(
        c,
        left + 3,
        top + 5,
        "SAVOLLAR KITOBCHASI IDENTIFIKATORI",
        size=6.5,
        bold=True,
        gray=True,
    )

    qr_size = 27

    qr_left = left + 4
    qr_top = top + 9

    draw_qr(
        c,
        exam_id=exam.exam_id,
        booklet_id=booklet.booklet_id,
        left_mm=qr_left,
        top_mm=qr_top,
        size_mm=qr_size
    )

    text_left = qr_left + qr_size + 6

    draw_text(
        c,
        text_left,
        top + 16,
        "BOOKLET ID",
        size=6,
        bold=True,
        gray=True,
    )

    draw_text(
        c,
        text_left,
        top + 23,
        booklet.booklet_id,
        size=11,
        bold=True,
    )

    draw_text(
        c,
        text_left,
        top + 30,
        "Imtihon ID",
        size=6,
        gray=True,
    )

    draw_text(
        c,
        text_left,
        top + 36,
        exam.exam_id,
        size=7,
        bold=True,
    )

    draw_text(
        c,
        text_left,
        top + 41,
        "QR kodni bo'ymang yoki yopmang.",
        size=5.5,
        gray=True,
    )


# ============================================================
# INSTRUCTIONS
# ============================================================

def draw_instructions(
    c,
):
    left = 11
    top = 83

    width = 188
    height = 25

    draw_box(
        c,
        left,
        top,
        width,
        height
    )

    draw_text(
        c,
        left + 3,
        top + 5,
        "JAVOBLARNI BELGILASH QOIDALARI",
        size=6.5,
        bold=True,
        gray=True,
    )

    draw_text(
        c,
        left + 3,
        top + 11,
        "1. Faqat bitta javobni belgilang.",
        size=6.3,
    )

    draw_text(
        c,
        left + 3,
        top + 17,
        "2. Bubble ichini to'liq va aniq bo'yang.",
        size=6.3,
    )

    draw_text(
        c,
        left + 65,
        top + 11,
        "3. Ikki yoki undan ortiq belgi noto'g'ri/noaniq javob hisoblanishi mumkin.",
        size=6.3,
    )

    draw_text(
        c,
        left + 65,
        top + 17,
        "4. Varaqani buklamang, yirtmang va QR/markerlarni yopmang.",
        size=6.3,
    )

    # Demo
    draw_filled_bubble(
        c,
        left + 165,
        top + 10,
        radius_mm=1.7
    )

    draw_text(
        c,
        left + 170,
        top + 11,
        "To'g'ri",
        size=6,
    )

    draw_bubble(
        c,
        left + 165,
        top + 17,
        radius_mm=1.7
    )

    draw_text(
        c,
        left + 170,
        top + 18,
        "Bo'sh", 
        size=6,
    )


# ============================================================
# ANSWER COLUMN
# ============================================================

def draw_answer_column(
    c,
    left_mm: float,
    top_mm: float,
    width_mm: float,
    height_mm: float,
    subject_block: Optional[SubjectBlock],
    max_rows: int = 30,
):
    """
    Bitta 30 savollik OMR ustuni.

    MUHIM (timing track): ustun BO'SH (subject_block is None) bo'lsa
    ham, timing marklar chiziladi -- chunki reader tomonida ustunlar
    orasidagi qator indekslash BARCHA ustunlarda bir xil bo'lishi
    kerak (aks holda find_timing_marks() ustun bo'yicha turlicha
    sondagi belgi topib, mos kelmay qoladi).
    """

    draw_box(
        c,
        left_mm,
        top_mm,
        width_mm,
        height_mm
    )

    # Table settings (BO'SH ustunda ham ishlatiladi -- timing track
    # header_h dan boshlanadi, xuddi to'ldirilgan ustundagi kabi)
    header_h = 18
    row_h = 4.25

    # Timing track -- har bir qator uchun, subject_block bor-yo'qligidan
    # qat'i nazar. Bu reader'ga arifmetik formulaga tayanmasdan
    # HAQIQIY qator y-markazini berish imkonini beradi.
    for i in range(max_rows):
        row_top = top_mm + header_h + i * row_h
        draw_timing_mark(
            c,
            left_mm + TIMING_MARK_OFFSET_MM,
            row_top + row_h / 2,
        )

    if subject_block is None:

        draw_text(
            c,
            left_mm + width_mm / 2,
            top_mm + 6,
            "BO'SH",
            size=8,
            bold=True,
            center=True,
            gray=True,
        )

        draw_text(
            c,
            left_mm + width_mm / 2,
            top_mm + 12,
            "Bu blok ishlatilmaydi",
            size=5.8,
            center=True,
            gray=True,
        )

        return

    # Header -- MUHIM: savol oralig'i ("1-30") endi ko'rsatilmaydi,
    # chunki bitta ustun har doim boshidan to'liq to'ldiriladi va
    # alohida oraliq yozuvi keraksiz/chalg'ituvchi edi.
    draw_text(
        c,
        left_mm + width_mm / 2,
        top_mm + 7,
        subject_block.subject,
        size=6.5,
        bold=True,
        center=True,
    )

    # Ball faqat BLOKDAGI BARCHA savollar BIR XIL ballga ega bo'lsa
    # ko'rsatiladi. Aks holda (mixed_points=True -- masalan bitta
    # ustunda 1.1/2.1/3.1 aralash) bu yozuv chiqarilmaydi, chunki
    # bitta raqam butun ustun "shu ballga ega" degan noto'g'ri
    # taassurot qoldirar edi -- haqiqiy ball har bir savolning o'z
    # `ball` maydonidan (DB'dan) olinadi va baholash shu asosda ishlaydi.
    if not subject_block.mixed_points:
        draw_text(
            c,
            left_mm + width_mm / 2,
            top_mm + 12,
            f"{subject_block.point:g} ball",
            size=5.8,
            center=True,
            gray=True,
        )

    question_x = left_mm + 6

    answer_x = [
        left_mm + 16,
        left_mm + 23,
        left_mm + 30,
        left_mm + 37,
    ]

    # Letters
    letters = ["A", "B", "C", "D"]

    for letter, lx in zip(letters, answer_x):
        draw_text(
            c,
            lx,
            top_mm + header_h - 2,
            letter,
            size=5.5,
            bold=True,
            center=True,
            gray=True,
        )

    # Question rows
    for i in range(max_rows):

        question_number = subject_block.start + i

        row_top = (
            top_mm
            + header_h
            + i * row_h
        )

        center_y = row_top + row_h / 2

        # Agar bu blok 30 dan kam savolga ega bo'lsa,
        # qolgan joy bo'sh qoladi.
        if question_number > subject_block.end:
            continue

        # Question number
        draw_text(
            c,
            question_x,
            center_y + 1.8,
            str(question_number),
            size=6,
            bold=True,
            center=True,
        )

        # Bubbles
        for bubble_x in answer_x:

            draw_bubble(
                c,
                bubble_x,
                center_y,
                radius_mm=1.75
            )

        # Row separator
        if i < max_rows - 1:

            draw_line(
                c,
                left_mm + 2,
                row_top + row_h,
                left_mm + width_mm - 2,
                row_top + row_h,
                width=0.15,
                gray=True
            )


# ============================================================
# SUBJECT DISTRIBUTION
# ============================================================

def distribute_subjects(
    exam: Exam,
) -> List[Optional[SubjectBlock]]:
    """
    Fan bloklarini 3 ta ustunga joylashtiradi.

    Masalan:

    30 savol:
        [Tarix 1-30, None, None]

    60 savol:
        [Tarix 1-30, Matematika 31-60, None]

    90 savol:
        [Tarix 1-30, Matematika 31-60, Fizika 61-90]
    """

    columns = [
        None,
        None,
        None
    ]

    for subject in exam.subjects:

        if subject.start <= 30:

            columns[0] = subject

        elif subject.start <= 60:

            columns[1] = subject

        elif subject.start <= 90:

            columns[2] = subject

    return columns


# ============================================================
# FOOTER
# ============================================================

def draw_footer(
    c,
    brand_name: str,
):
    top = 263

    draw_line(
        c,
        11,
        top,
        199,
        top,
        width=0.3,
        gray=True
    )

    draw_text(
        c,
        11,
        top + 5,
        "ESLATMA:",
        size=5.8,
        bold=True,
        gray=True,
    )

    draw_text(
        c,
        26,
        top + 5,
        "Javoblar varaqasini buklamang, yirtmang yoki QR va qora markerlarni yopmang.",
        size=5.8,
        gray=True,
    )

    draw_text(
        c,
        11,
        top + 10,
        "Chop etish:",
        size=5.8,
        bold=True,
        gray=True,
    )

    draw_text(
        c,
        28,
        top + 10,
        "A4, 100% / Actual Size. Fit to Page ishlatilmasin.",
        size=5.8,
        gray=True,
    )

    draw_text(
        c,
        105,
        top + 17,
        brand_name,
        size=5.5,
        center=True,
        gray=True,
    )


# ============================================================
# MAIN GENERATOR
# ============================================================

def generate_answer_sheet(
    output_path: str,
    student: Student,
    exam: Exam,
    booklet: Booklet,
    brand_name: str = "BRAND NAME",
):
    """
    Javoblar varaqasini PDF qilib yaratadi.
    """

    output = Path(output_path)

    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    c = canvas.Canvas(
        str(output),
        pagesize=A4
    )

    # 1. Registration markers
    draw_registration_markers(c)

    # 2. Header
    draw_header(
        c,
        exam=exam,
        brand_name=brand_name
    )

    # 3. Student info (+ fanlar / ball / savollar soni)
    draw_student_info(
        c,
        student=student,
        exam=exam,
    )

    # 4. QR
    draw_qr_box(
        c,
        exam=exam,
        booklet=booklet
    )

    # 5. Instructions
    draw_instructions(c)

    # 6. Subject columns
    columns = distribute_subjects(exam)

    # Answer area
    column_lefts = [
        11,
        56,
        101,
    ]

    column_width = 42

    answer_top = 111
    answer_height = 148

    for index, subject_block in enumerate(columns):

        draw_answer_column(
            c,
            left_mm=column_lefts[index],
            top_mm=answer_top,
            width_mm=column_width,
            height_mm=answer_height,
            subject_block=subject_block,
            max_rows=30,
        )

    # 7. Supervisor / student signature area
    draw_box(
        c,
        146,
        111,
        53,
        151
    )

    draw_text(
        c,
        172.5,
        118,
        "NAZORATCHI",
        size=7,
        bold=True,
        center=True,
    )

    draw_text(
        c,
        172.5,
        125,
        "Imzo:",
        size=6,
        center=True,
        gray=True,
    )

    draw_dashed_line(
        c,
        153,
        130,
        192
    )

    draw_text(
        c,
        172.5,
        138,
        "ABITURIYENT",
        size=7,
        bold=True,
        center=True,
    )

    draw_text(
        c,
        172.5,
        145,
        "Ruchkada to'ldiriladi",
        size=5.5,
        center=True,
        gray=True,
    )

    fields = [
        "Ism",
        "Familiya",
        "Otasining ismi",
        "Imzo",
    ]

    field_top = 153

    for field_name in fields:

        draw_text(
            c,
            150,
            field_top,
            field_name,
            size=6,
            gray=True,
        )

        draw_dashed_line(
            c,
            150,
            field_top + 5,
            195
        )

        field_top += 17

    # 8. Footer
    draw_footer(
        c,
        brand_name
    )

    # Finish
    c.showPage()
    c.save()

    return str(output)


# ============================================================
# DEMO
# ============================================================

if __name__ == "__main__":

    # ----------------------------------------
    # Student
    # ----------------------------------------

    student = Student(
        id="STU-001",
        first_name="Nilufar",
        last_name="Karimova",
        father_name="Botir qizi",
        group_name="10-A",
    )

    # ----------------------------------------
    # Exam
    # ----------------------------------------

    exam = Exam(
        exam_id="EX-2026-0417",
        exam_name="Yakuniy nazorat testi",
        total_questions=90,

        subjects=[
            SubjectBlock(
                start=1,
                end=30,
                subject="Tarix",
                point=1.1,
            ),

            SubjectBlock(
                start=31,
                end=60,
                subject="Matematika",
                point=1.1,
            ),

            SubjectBlock(
                start=61,
                end=90,
                subject="Fizika",
                point=2.1,
            ),
        ],
    )

    # ----------------------------------------
    # Booklet
    # ----------------------------------------

    booklet = Booklet(
        booklet_id="3817294",
        exam_id=exam.exam_id,
        student_id=student.id,
    )

    # ----------------------------------------
    # Generate
    # ----------------------------------------

    output_file = generate_answer_sheet(
        output_path="output/javoblar_varaqasi.pdf",
        student=student,
        exam=exam,
        booklet=booklet,
        brand_name="SAFAR TEST",
    )

    print(
        f"Javoblar varaqasi tayyor: {output_file}"
    )