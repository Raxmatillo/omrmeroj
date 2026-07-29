# drawers.py
import reportlab.pdfgen.canvas as canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.graphics.shapes import Drawing, Rect, Circle
from io import BytesIO
import cv2
import numpy as np
from PIL import Image as PILImage
from config import LayoutConfig
from layout_engine import LayoutEngine
from typing import List, Dict, Tuple
import math

# ----------------------------------------------------------------------
# Helper: convert mm to points
def mm2pt(mm_val: float) -> float:
    return mm_val / 25.4 * 72.0  # 1 inch = 25.4 mm = 72 pt

class BaseDrawer:
    def __init__(self, config: LayoutConfig, engine: LayoutEngine, canvas: canvas.Canvas):
        self.cfg = config
        self.engine = engine
        self.canvas = canvas
        self.metadata: List[Dict] = []  # accumulate metadata per drawing operation

    def _draw_bubble(self, x_mm: float, y_mm: float, radius_mm: float, stroke_width_mm: float = None):
        """Draw an empty bubble (circle) and return its metadata entry."""
        if stroke_width_mm is None:
            stroke_width_mm = self.cfg.bubble_stroke_width_mm
        self.canvas.setLineWidth(mm2pt(stroke_width_mm))
        self.canvas.setStrokeColor(colors.black)
        self.canvas.setFillColor(colors.white)
        center_x = mm2pt(x_mm)
        center_y = mm2pt(self.cfg.page_height_mm - y_mm)  # invert y for PDF coordinates
        radius_pt = mm2pt(radius_mm)
        self.canvas.circle(center_x, center_y, radius_pt, fill=1, stroke=1)
        return {"x": x_mm, "y": y_mm, "radius": radius_mm}

    def _draw_filled_rect(self, x_mm: float, y_mm: float, w_mm: float, h_mm: float):
        """Filled black rectangle for locator markers or ArUco cells."""
        self.canvas.setFillColor(colors.black)
        self.canvas.setStrokeColor(colors.black)
        self.canvas.rect(mm2pt(x_mm), mm2pt(self.cfg.page_height_mm - y_mm - h_mm),
                         mm2pt(w_mm), mm2pt(h_mm), fill=1, stroke=0)

    def _draw_text(self, x_mm: float, y_mm: float, text: str, font_size: int = None, font_name: str = "Helvetica",
                   align: str = "left"):
        """Draw text at given position (y measured from top)."""
        if font_size is None:
            font_size = self.cfg.font_size_normal
        self.canvas.setFont(font_name, font_size)
        self.canvas.setFillColor(colors.black)
        y_pdf = self.cfg.page_height_mm - y_mm
        if align == "left":
            self.canvas.drawString(mm2pt(x_mm), mm2pt(y_pdf), text)
        elif align == "center":
            text_width = stringWidth(text, font_name, font_size)
            self.canvas.drawString(mm2pt(x_mm) - text_width/2, mm2pt(y_pdf), text)
        elif align == "right":
            text_width = stringWidth(text, font_name, font_size)
            self.canvas.drawString(mm2pt(x_mm) - text_width, mm2pt(y_pdf), text)

    def _text_height(self, text: str, font_size: int = None, font_name: str = "Helvetica") -> float:
        """Approximate height of a line of text in mm."""
        if font_size is None:
            font_size = self.cfg.font_size_normal
        # ReportLab font size in points ≈ text height in points. Convert to mm.
        return (font_size / 72.0) * 25.4

class HeaderDrawer(BaseDrawer):
    def draw(self) -> float:
        """Draw title and exam name, return height used."""
        title = "JAVOBLAR VARAQASI"
        subtitle = self.cfg.exam_name
        title_size = self.cfg.font_size_title
        sub_size = self.cfg.font_size_subtitle
        title_h = self._text_height(title, title_size) + 4  # extra spacing
        sub_h = self._text_height(subtitle, sub_size) + 2
        total_h = title_h + sub_h
        x, y, w, h = self.engine.reserve_space(total_h)
        # center horizontally
        center_x = x + w / 2
        self._draw_text(center_x, y + title_h/2, title, font_size=title_size, align="center")
        self._draw_text(center_x, y + title_h + sub_h/2, subtitle, font_size=sub_size, align="center")
        return total_h

class StudentDrawer(BaseDrawer):
    def draw(self, left_rect: Tuple[float, float, float, float]) -> float:
        """Draw student name field."""
        x, y, w, h = left_rect
        line_y = y + 15  # offset for label
        self._draw_text(x, y, "O'quvchi ismi", self.cfg.font_size_normal)
        # underline
        self.canvas.setLineWidth(0.5)
        self.canvas.line(mm2pt(x), mm2pt(self.cfg.page_height_mm - line_y),
                         mm2pt(x + w), mm2pt(self.cfg.page_height_mm - line_y))
        # class info
        class_y = line_y + 10
        self._draw_text(x, class_y, "Sinf: __________", self.cfg.font_size_normal)
        group_y = class_y + 8
        self._draw_text(x, group_y, "Guruh: __________", self.cfg.font_size_normal)
        return h  # height reserved already

class ExamDrawer(BaseDrawer):
    def draw(self, right_rect: Tuple[float, float, float, float]) -> float:
        """Draw exam info: subjects, scores, question count."""
        x, y, w, h = right_rect
        current_y = y
        self._draw_text(x, current_y, "Fanlar", self.cfg.font_size_normal)
        current_y += 8
        for subj in self.cfg.subjects:
            self._draw_text(x + 5, current_y, subj, self.cfg.font_size_normal)
            current_y += 7
        current_y += 5
        # scores
        if self.cfg.score_mode == "per_subject" and self.cfg.subject_scores:
            self._draw_text(x, current_y, "Ballar", self.cfg.font_size_normal)
            current_y += 8
            for subj, score in self.cfg.subject_scores.items():
                self._draw_text(x + 5, current_y, f"{subj}: {score}", self.cfg.font_size_normal)
                current_y += 7
        elif self.cfg.score_mode == "overall" and self.cfg.overall_max_score is not None:
            self._draw_text(x, current_y, f"Maks. ball: {self.cfg.overall_max_score}", self.cfg.font_size_normal)
            current_y += 10
        # question count
        current_y += 5
        self._draw_text(x, current_y, f"Savollar: {self.cfg.total_questions}", self.cfg.font_size_normal)
        return h  # height is pre-reserved, but we could adjust

class BookletDrawer(BaseDrawer):
    def draw(self) -> Tuple[float, List[Dict]]:
        """Draw 7-digit booklet ID bubbles, return height used and metadata."""
        num_digits = self.cfg.booklet_digits
        digit_width = (self.cfg.bubble_radius_mm * 2) + 2  # bubble diameter + small padding
        column_width = digit_width + self.cfg.booklet_digit_gap_mm
        total_width = num_digits * column_width - self.cfg.booklet_digit_gap_mm
        # center horizontally
        start_x = self.engine.content_left + (self.engine.content_width - total_width) / 2
        start_y = self.engine.current_y() + 8  # small top margin
        row_height = self.cfg.row_height_mm  # distance between bubbles 0-9
        # draw digits
        bubble_radius = self.cfg.bubble_radius_mm
        for d in range(num_digits):
            digit_x = start_x + d * column_width
            label_y = start_y
            self._draw_text(digit_x + digit_width/2, label_y, str(d+1), self.cfg.font_size_small, align="center")
            digit_bubble_start_y = label_y + 5
            for value in range(10):
                bubble_y = digit_bubble_start_y + value * row_height
                entry = self._draw_bubble(digit_x + digit_width/2, bubble_y, bubble_radius)
                entry["digit"] = d + 1
                entry["value"] = value
                self.metadata.append(entry)
        # compute total height used
        total_h = (label_y - start_y) + 5 + 10 * row_height  # from start_y to last bubble bottom
        self.engine.set_y(start_y + total_h)
        return total_h, self.metadata

class VariantDrawer(BaseDrawer):
    def draw(self) -> Tuple[float, List[Dict]]:
        """Draw variant selection bubbles A-E horizontally."""
        variants = ['A', 'B', 'C', 'D', 'E']
        bubble_diam = self.cfg.bubble_radius_mm * 2
        total_width = len(variants) * (bubble_diam + self.cfg.variant_gap_mm) - self.cfg.variant_gap_mm
        start_x = self.engine.content_left + (self.engine.content_width - total_width) / 2
        start_y = self.engine.current_y() + 5
        for i, variant in enumerate(variants):
            cx = start_x + i * (bubble_diam + self.cfg.variant_gap_mm) + bubble_diam/2
            cy = start_y
            entry = self._draw_bubble(cx, cy, self.cfg.bubble_radius_mm)
            entry["variant"] = variant
            self.metadata.append(entry)
            # variant label below bubble
            label_y = cy + self.cfg.bubble_radius_mm + 2
            self._draw_text(cx, label_y, variant, self.cfg.font_size_small, align="center")
        total_h = (start_y - self.engine.current_y()) + 15  # from previous y
        self.engine.set_y(start_y + 12)  # after variant
        return total_h, self.metadata

class InstructionDrawer(BaseDrawer):
    def draw(self) -> float:
        """Draw instruction block."""
        instructions = [
            "Faqat ko'k yoki qora ruchkadan foydalaning.",
            "Doiralarni to'liq bo'yang.",
            "Bir savolga bir nechta javob belgilamang.",
            "Qog'ozni buklamang.",
            "Burchaklarni shikastlamang.",
        ]
        start_y = self.engine.current_y() + 5
        self._draw_text(self.engine.content_left, start_y, "Ko'rsatmalar:", self.cfg.font_size_normal, font_name="Helvetica-Bold")
        line_y = start_y + 8
        for line in instructions:
            self._draw_text(self.engine.content_left + 5, line_y, line, self.cfg.font_size_small)
            line_y += 5
        total_h = line_y - self.engine.current_y()
        self.engine.set_y(line_y + 3)
        return total_h

class AnswerGridDrawer(BaseDrawer):
    def draw(self, total_questions: int) -> Tuple[float, List[Dict]]:
        """Draw answer grid with locator, question number, bubbles; return height and metadata."""
        # Determine number of columns
        columns = 1
        for q_count, cols in sorted(self.cfg.question_columns.items(), reverse=True):
            if total_questions >= q_count:
                columns = cols
                break

        questions_per_column = math.ceil(total_questions / columns)
        options = self.cfg.options
        bubble_radius = self.cfg.bubble_radius_mm
        bubble_diam = bubble_radius * 2
        locator_size = self.cfg.locator_size_mm
        # Horizontal layout of one answer row:
        # [locator] gap [question number] gap [A bubble] gap [B bubble] ...
        locator_x_offset = locator_size + 2   # from left edge of column
        number_width = 10  # approx mm for two-digit number
        bubble_group_start = locator_x_offset + number_width + 4
        # compute total row width
        group_width = len(options) * (bubble_diam + self.cfg.bubble_gap_mm) - self.cfg.bubble_gap_mm
        row_width_needed = bubble_group_start + group_width
        # column width from config is given, ensure it's enough
        column_width = max(self.cfg.column_width_mm, row_width_needed + 2)
        # actual column width used
        total_grid_width = columns * column_width
        start_x = self.engine.content_left + (self.engine.content_width - total_grid_width) / 2
        start_y = self.engine.current_y() + 5

        row_h = self.cfg.row_height_mm
        metadata = []

        for col in range(columns):
            col_x = start_x + col * column_width
            for q_in_col in range(questions_per_column):
                q_num = col * questions_per_column + q_in_col + 1
                if q_num > total_questions:
                    break
                row_y = start_y + q_in_col * row_h
                # locator marker
                locator_x = col_x
                self._draw_filled_rect(locator_x, row_y - locator_size/2, locator_size, locator_size)
                # question number
                num_x = col_x + locator_x_offset
                self._draw_text(num_x, row_y, str(q_num), self.cfg.font_size_small, align="left")
                # bubbles
                bubble_center_x = col_x + bubble_group_start
                for i, opt in enumerate(options):
                    bx = bubble_center_x + i * (bubble_diam + self.cfg.bubble_gap_mm) + bubble_radius
                    by = row_y
                    entry = self._draw_bubble(bx, by, bubble_radius)
                    entry["question"] = q_num
                    entry["option"] = opt
                    metadata.append(entry)

        total_h = questions_per_column * row_h
        self.engine.set_y(start_y + total_h + 10)
        return total_h, metadata

# drawers.py fayliga qo‘shing (yoki mavjud MarkerDrawer o‘rniga)
from reportlab.lib.units import mm
from reportlab.lib import colors

class MarkerDrawer(BaseDrawer):
    """ArUco 4x4_50 markerlarini ReportLab vositasida chizadi (OpenCV kerak emas)."""

    def __init__(self, config, engine, canvas):
        super().__init__(config, engine, canvas)
        self.marker_size_mm = self.cfg.aruco_marker_size_mm
        # DICT_4X4_50 marker kodlari (0,1,2,3 uchun 4x4 binary matritsalar)
        # Manba: OpenCV kodidan olindi yoki onlayn generator bilan tekshirilgan.
        self.marker_patterns = {
            0: [[0, 1, 0, 0],
                [1, 0, 1, 1],
                [0, 1, 1, 0],
                [0, 0, 1, 0]],
            1: [[1, 0, 0, 1],
                [0, 1, 1, 0],
                [0, 1, 0, 1],
                [1, 0, 1, 0]],
            2: [[0, 1, 1, 0],
                [1, 0, 0, 1],
                [1, 0, 1, 0],
                [0, 1, 0, 1]],
            3: [[1, 0, 1, 1],
                [0, 1, 0, 0],
                [1, 0, 0, 1],
                [1, 1, 0, 0]],
        }

    def draw(self):
        """To‘rt burchakka markerlarni joylashtirish va metadata qaytarish."""
        markers_meta = []
        half = self.marker_size_mm / 2
        margin = self.cfg.aruco_margin_mm
        positions = {
            0: (margin + half, margin + half),                           # yuqori-chap
            1: (self.cfg.page_width_mm - margin - half, margin + half),  # yuqori-o‘ng
            2: (self.cfg.page_width_mm - margin - half, self.cfg.page_height_mm - margin - half), # past-o‘ng
            3: (margin + half, self.cfg.page_height_mm - margin - half), # past-chap
        }
        for marker_id, (cx, cy) in positions.items():
            self._draw_aruco_marker(marker_id, cx, cy)
            markers_meta.append({
                "marker_id": marker_id,
                "x": cx,
                "y": cy,
                "size": self.marker_size_mm
            })
        return markers_meta

    def _draw_aruco_marker(self, marker_id, center_x_mm, center_y_mm):
        """Berilgan ID va markaz koordinatasi bo‘yicha marker chizish."""
        pattern = self.marker_patterns[marker_id]
        # Marker 6x6 katakchali tuzilish: tashqi qora chegara (1 katak), ichki 4x4 oq/qora.
        # Biz tashqi chegarani alohida to‘ldirilgan to‘rtburchak sifatida chizamiz,
        # so‘ngra har bir ichki katakchani rangiga qarab chizamiz.
        total_cells = 6  # tashqi chegara + 4 ichki
        cell_size_mm = self.marker_size_mm / total_cells

        # Yuqori-chap burchak koordinatasi (mm)
        top_left_x = center_x_mm - self.marker_size_mm / 2
        top_left_y = center_y_mm - self.marker_size_mm / 2  # pastga qarab y

        # 1. Tashqi qora chegara (butun maydonni qora to‘ldiramiz)
        self.canvas.setFillColor(colors.black)
        self.canvas.rect(mm2pt(top_left_x),
                         mm2pt(self.cfg.page_height_mm - (top_left_y + self.marker_size_mm)),
                         mm2pt(self.marker_size_mm),
                         mm2pt(self.marker_size_mm),
                         fill=1, stroke=0)

        # 2. Ichki oq fon (tashqi chegaradan 1 katak ichkarida)
        inner_offset = cell_size_mm
        inner_size = self.marker_size_mm - 2 * cell_size_mm
        self.canvas.setFillColor(colors.white)
        self.canvas.rect(mm2pt(top_left_x + inner_offset),
                         mm2pt(self.cfg.page_height_mm - (top_left_y + inner_offset + inner_size)),
                         mm2pt(inner_size),
                         mm2pt(inner_size),
                         fill=1, stroke=0)

        # 3. 4x4 bitlarni chizish (qora katakchalar)
        self.canvas.setFillColor(colors.black)
        for row in range(4):
            for col in range(4):
                if pattern[row][col] == 1:
                    cell_x = top_left_x + inner_offset + col * cell_size_mm
                    cell_y = top_left_y + inner_offset + row * cell_size_mm
                    # ReportLab rect: x, y (pastki-chap burchak), kenglik, balandlik
                    self.canvas.rect(mm2pt(cell_x),
                                     mm2pt(self.cfg.page_height_mm - (cell_y + cell_size_mm)),
                                     mm2pt(cell_size_mm),
                                     mm2pt(cell_size_mm),
                                     fill=1, stroke=0)