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
  shu belgining haqiqiy (siyohdagi) markazidan o'qiydi.
- TEST VARIANTI: talabaga tayinlangan variant raqamini (1/2/3/4) o'zi
  bo'yab belgilaydigan kichik 4 ta bubble ("Ko'rsatmalar" ramkasi
  yonida) -- app/omr/omr_reader.py shu bubble'larni ham o'qiydi va
  ExamStudent.paper_variant_number bilan solishtiradi (nomuvofiqlik
  bo'lsa natija "tekshirish kerak" deb belgilanadi).

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

# ------------------------------------------------------------------
# TEST VARIANTI bubble maydoni ("Ko'rsatmalar" ramkasi endi to'liq
# kenglikni EGALLAMAYDI -- o'ng tomonida shu kichik box qoladi).
# ------------------------------------------------------------------
INSTRUCTIONS_LEFT_MM = 11.0
INSTRUCTIONS_TOP_MM = 83.0
INSTRUCTIONS_WIDTH_MM = 108.0
INSTRUCTIONS_HEIGHT_MM = 25.0

_INSTR_VARIANT_GAP_MM = 2.0
VARIANT_BOX_LEFT_MM = INSTRUCTIONS_LEFT_MM + INSTRUCTIONS_WIDTH_MM + _INSTR_VARIANT_GAP_MM  # 121.0
VARIANT_BOX_TOP_MM = INSTRUCTIONS_TOP_MM  # 83.0
VARIANT_BOX_WIDTH_MM = 199.0 - VARIANT_BOX_LEFT_MM  # ~78.0
VARIANT_BOX_HEIGHT_MM = INSTRUCTIONS_HEIGHT_MM  # 25.0

# 4 ta bubble markazining X koordinatasi (mm, sahifa chap chetidan)
VARIANT_BUBBLE_XS_MM = [133.0, 151.0, 169.0, 187.0]
VARIANT_BUBBLE_Y_MM = VARIANT_BOX_TOP_MM + 19.0  # 102.0
VARIANT_BUBBLE_RADIUS_MM = 2.2

MAX_PAPER_VARIANTS = len(VARIANT_BUBBLE_XS_MM)  # 4


# Variant bubble'lari uchun TIMING MARK -- omr_reader shu belgilardan
# har bir bubble'ning HAQIQIY x/y markazini topadi (asosiy javob
# ustunlaridagi timing track bilan bir xil mantiq). Bubble markazidan
# pastga TIMING_MARK_OFFSET masofada joylashadi.
VARIANT_TIMING_MARK_OFFSET_MM = 3.6
VARIANT_TIMING_MARK_SIZE_MM = TIMING_MARK_SIZE_MM  # 1.4 -- bir xil o'lcham

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
    # savollarni birlashtirgan. Bunday holda `point` ustun boshida
    # ko'rsatilmaydi (draw_answer_column shu bayroqni tekshiradi).
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

    subjects: List[SubjectBlock] = field(
        default_factory=list
    )

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

    variant_number -- talabaga tayinlangan "TEST VARIANTI" (1..4,
    ixtiyoriy). Javoblar varag'ida bu raqam OLDINDAN chizilmaydi --
    talabaning o'zi tegishli bubble'ni bo'yab belgilaydi (savollar
    kitobchasida shu raqam ko'rsatiladi va "shuni belgilang" deb
    ko'rsatma beriladi). Shu sababli bu maydon hozircha faqat
    ma'lumot uchun saqlanadi (kelajakda QR ichiga qo'shish kabi
    ishlarga moslashuvchan bo'lishi uchun).
    """

    booklet_id: str
    exam_id: str
    student_id: str
    variant_number: Optional[int] = None


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

    subjects = exam._breakdown_or_subjects

    table_top = cursor_top
    table_bottom = top + height - 2
    available_height = table_bottom - table_top

    total_rows = len(subjects) + 2

    if total_rows <= 0 or available_height <= 0:
        return

    row_h = available_height / total_rows

    font_size = max(6.0, min(8.5, row_h * 1.55))
    header_font_size = max(5.2, min(7.0, font_size - 1.3))

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

    for i, subject in enumerate(subjects):

        subject_name = subject.subject

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
# INSTRUCTIONS (endi ORQA butun kenglikni EGALLAMAYDI --
# o'ng tomonda TEST VARIANTI bubble maydoni uchun joy qoldiriladi)
# ============================================================

def draw_instructions(
    c,
):
    left = INSTRUCTIONS_LEFT_MM
    top = INSTRUCTIONS_TOP_MM
    width = INSTRUCTIONS_WIDTH_MM
    height = INSTRUCTIONS_HEIGHT_MM

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
        size=6.3,
        bold=True,
        gray=True,
    )

    lines = [
        "1. Faqat bitta javobni belgilang.",
        "2. Bubble ichini to'liq va aniq bo'yang.",
        "3. Ikki yoki undan ortiq belgi - xato hisoblanadi.",
        "4. Varaqani buklamang, yirtmang, QR/markerlarni yopmang.",
    ]

    ly = top + 9.8
    for line in lines:
        draw_text(c, left + 3, ly, line, size=5.7)
        ly += 3.7


# ============================================================
# TEST VARIANTI BELGILASH MAYDONI (YANGI)
# ============================================================

def draw_variant_marking(c):
    left = VARIANT_BOX_LEFT_MM
    top = VARIANT_BOX_TOP_MM
    width = VARIANT_BOX_WIDTH_MM
    height = VARIANT_BOX_HEIGHT_MM

    draw_box(c, left, top, width, height)

    draw_text(
        c, left + width / 2, top + 5, "TEST VARIANTI",
        size=6.3, bold=True, center=True, gray=True,
    )
    draw_text(
        c, left + width / 2, top + 9.3, "(kitobchadagi raqamni belgilang)",
        size=5.0, center=True, gray=True,
    )

    labels = ["1", "2", "3", "4"]
    label_y = VARIANT_BUBBLE_Y_MM - 5.5

    for label, cx in zip(labels, VARIANT_BUBBLE_XS_MM):
        draw_text(c, cx, label_y, label, size=6.5, bold=True, center=True)
        draw_bubble(c, cx, VARIANT_BUBBLE_Y_MM, radius_mm=VARIANT_BUBBLE_RADIUS_MM)
        # YANGI: reader shu belgidan bubble qatorining haqiqiy y-markazini
        # (va keyin Hough orqali x-markazini) topadi.
        draw_timing_mark(
            c, cx, VARIANT_BUBBLE_Y_MM + VARIANT_TIMING_MARK_OFFSET_MM,
            size_mm=VARIANT_TIMING_MARK_SIZE_MM,
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
    draw_box(
        c,
        left_mm,
        top_mm,
        width_mm,
        height_mm
    )

    header_h = 18
    row_h = 4.25

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

    draw_text(
        c,
        left_mm + width_mm / 2,
        top_mm + 7,
        subject_block.subject,
        size=6.5,
        bold=True,
        center=True,
    )

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

    for i in range(max_rows):

        question_number = subject_block.start + i

        row_top = (
            top_mm
            + header_h
            + i * row_h
        )

        center_y = row_top + row_h / 2

        if question_number > subject_block.end:
            continue

        draw_text(
            c,
            question_x,
            center_y + 1.8,
            str(question_number),
            size=6,
            bold=True,
            center=True,
        )

        for bubble_x in answer_x:

            draw_bubble(
                c,
                bubble_x,
                center_y,
                radius_mm=1.75
            )

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

    draw_registration_markers(c)

    draw_header(
        c,
        exam=exam,
        brand_name=brand_name
    )

    draw_student_info(
        c,
        student=student,
        exam=exam,
    )

    draw_qr_box(
        c,
        exam=exam,
        booklet=booklet
    )

    draw_instructions(c)
    draw_variant_marking(c)

    columns = distribute_subjects(exam)

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

    draw_footer(
        c,
        brand_name
    )

    c.showPage()
    c.save()

    return str(output)


# ============================================================
# DEMO
# ============================================================

if __name__ == "__main__":

    student = Student(
        id="STU-001",
        first_name="Nilufar",
        last_name="Karimova",
        father_name="Botir qizi",
        group_name="10-A",
    )

    exam = Exam(
        exam_id="EX-2026-0417",
        exam_name="Yakuniy nazorat testi",
        total_questions=90,

        subjects=[
            SubjectBlock(start=1, end=30, subject="Tarix", point=1.1),
            SubjectBlock(start=31, end=60, subject="Matematika", point=1.1),
            SubjectBlock(start=61, end=90, subject="Fizika", point=2.1),
        ],
    )

    booklet = Booklet(
        booklet_id="3817294",
        exam_id=exam.exam_id,
        student_id=student.id,
        variant_number=2,
    )

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