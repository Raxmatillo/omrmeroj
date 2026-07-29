from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.graphics.barcode import qr

########################################################################
# CONFIG
########################################################################

PAGE_WIDTH = 210 * mm
PAGE_HEIGHT = 297 * mm

LEFT = 12 * mm
RIGHT = 198 * mm

TOP = 285 * mm
BOTTOM = 12 * mm

BUBBLE_RADIUS = 2.2 * mm
BUBBLE_SPACE = 6.2 * mm

ROW_HEIGHT = 8.0 * mm

FONT = "Helvetica"

TITLE_FONT = 20
NORMAL_FONT = 10
SMALL_FONT = 8

BORDER_COLOR = HexColor("#222222")

########################################################################
# DATA MODELS
########################################################################

@dataclass
class Subject:

    name: str

    question_count: int

    score: int


@dataclass
class ExamInfo:

    school_name: str

    exam_name: str

    grade: str

    class_name: str

    total_questions: int

    total_score: int

    subjects: List[Subject]


@dataclass
class SheetInfo:

    student_name: str = ""

    booklet_digits: int = 7

    variant_count: int = 5

########################################################################
# LAYOUT METADATA
########################################################################

class LayoutMetadata:

    def __init__(self):

        self.data = {

            "version": 2,

            "page": {

                "width": PAGE_WIDTH,

                "height": PAGE_HEIGHT

            },

            "markers": [],

            "bubbles": [],

            "blocks": []

        }

    def add_block(self, name, x, y, w, h):

        self.data["blocks"].append({

            "name": name,

            "x": x,

            "y": y,

            "width": w,

            "height": h

        })

    def add_bubble(

            self,

            bubble_type,

            x,

            y,

            radius,

            meta

    ):

        self.data["bubbles"].append({

            "type": bubble_type,

            "x": x,

            "y": y,

            "radius": radius,

            "meta": meta

        })

    def save(self, filename):

        with open(filename, "w", encoding="utf8") as f:

            json.dump(

                self.data,

                f,

                ensure_ascii=False,

                indent=4

            )

########################################################################
# GENERATOR
########################################################################

class AnswerSheetGenerator:

    def __init__(

            self,

            exam: ExamInfo,

            sheet: SheetInfo

    ):

        self.exam = exam

        self.sheet = sheet

        self.meta = LayoutMetadata()

    ####################################################################
    # DRAW HELPERS
    ####################################################################

    def circle(

            self,

            c,

            x,

            y,

            r=BUBBLE_RADIUS

    ):

        c.circle(

            x,

            y,

            r,

            stroke=1,

            fill=0

        )

    def filled_square(

            self,

            c,

            x,

            y,

            size=3.5 * mm

    ):

        c.setFillColor(black)

        c.rect(

            x,

            y,

            size,

            size,

            stroke=0,

            fill=1

        )

        c.setFillColor(black)

    def section_title(

            self,

            c,

            title,

            x,

            y

    ):

        c.setFont(

            FONT,

            12

        )

        c.drawString(

            x,

            y,

            title

        )

    ####################################################################
    # PAGE BORDER
    ####################################################################

    def draw_border(

            self,

            c

    ):

        c.setStrokeColor(

            BORDER_COLOR

        )

        c.setLineWidth(1)

        c.rect(

            8 * mm,

            8 * mm,

            PAGE_WIDTH - 16 * mm,

            PAGE_HEIGHT - 16 * mm

        )

    ####################################################################
    # TITLE
    ####################################################################

    def draw_title(

            self,

            c

    ):

        c.setFont(

            "Helvetica-Bold",

            TITLE_FONT

        )

        c.drawCentredString(

            PAGE_WIDTH / 2,

            279 * mm,

            "JAVOBLAR VARAQASI"

        )

        c.setFont(

            FONT,

            10

        )

        c.drawCentredString(

            PAGE_WIDTH / 2,

            273 * mm,

            self.exam.exam_name

        )

    ####################################################################
    # STUDENT INFO
    ####################################################################

    def draw_student_block(

            self,

            c

    ):

        x = 15 * mm

        y = 257 * mm

        self.section_title(

            c,

            "O'quvchi ma'lumotlari",

            x,

            y

        )

        y -= 8 * mm

        c.drawString(

            x,

            y,

            "Ism familiya :"

        )

        c.line(

            x + 35 * mm,

            y - 1,

            110 * mm,

            y - 1

        )

        y -= 8 * mm

        c.drawString(

            x,

            y,

            "Sinf / Guruh :"

        )

        c.line(

            x + 35 * mm,

            y - 1,

            75 * mm,

            y - 1

        )

        self.meta.add_block(

            "student",

            x,

            y,

            100 * mm,

            22 * mm

        )

    ####################################################################
    # EXAM INFO
    ####################################################################

    def draw_exam_info(

            self,

            c

    ):

        x = 118 * mm

        y = 257 * mm

        self.section_title(

            c,

            "Imtihon ma'lumotlari",

            x,

            y

        )

        y -= 8 * mm

        c.drawString(

            x,

            y,

            f"Savollar : {self.exam.total_questions}"

        )

        y -= 6 * mm

        c.drawString(

            x,

            y,

            f"Ball : {self.exam.total_score}"

        )

        y -= 6 * mm

        c.drawString(

            x,

            y,

            f"Sinf : {self.exam.grade}"

        )

        self.meta.add_block(

            "exam",

            x,

            y,

            60 * mm,

            24 * mm

        )