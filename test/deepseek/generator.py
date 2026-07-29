# generator.py
import json
from config import LayoutConfig
from layout_engine import LayoutEngine
from drawers import (
    HeaderDrawer, StudentDrawer, ExamDrawer, BookletDrawer,
    VariantDrawer, InstructionDrawer, AnswerGridDrawer, MarkerDrawer
)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from typing import Dict, Any

class AnswerSheetGenerator:
    def __init__(self, config: LayoutConfig = None):
        if config is None:
            config = LayoutConfig()
        self.cfg = config
        self.engine = LayoutEngine(config)
        self.metadata = {
            "page": {
                "width_mm": config.page_width_mm,
                "height_mm": config.page_height_mm
            },
            "blocks": {}
        }

    def generate(self):
        c = canvas.Canvas(self.cfg.pdf_filename, pagesize=A4)
        c.setTitle("Answer Sheet")

        # Instantiate drawers
        header = HeaderDrawer(self.cfg, self.engine, c)
        student = StudentDrawer(self.cfg, self.engine, c)
        exam = ExamDrawer(self.cfg, self.engine, c)
        booklet = BookletDrawer(self.cfg, self.engine, c)
        variant = VariantDrawer(self.cfg, self.engine, c)
        instructions = InstructionDrawer(self.cfg, self.engine, c)
        answer_grid = AnswerGridDrawer(self.cfg, self.engine, c)
        marker = MarkerDrawer(self.cfg, self.engine, c)

        # 1. Header
        header.draw()

        # 2. Two-column: student left, exam right
        # Calculate needed heights
        left_h = 38  # estimated for student info (will be anyway given reserved space)
        right_h = 10 + len(self.cfg.subjects) * 7 + 40  # rough for exam
        if self.cfg.score_mode == "per_subject" and self.cfg.subject_scores:
            right_h += len(self.cfg.subject_scores) * 7 + 10
        left_rect, right_rect = self.engine.reserve_two_column_space(left_h, right_h)
        student.draw(left_rect)
        exam.draw(right_rect)

        # 3. Booklet ID
        booklet_h, booklet_meta = booklet.draw()
        self.metadata["blocks"]["booklet"] = booklet_meta

        # 4. Variant
        variant_h, variant_meta = variant.draw()
        self.metadata["blocks"]["variant"] = variant_meta

        # 5. Instructions
        instructions.draw()

        # 6. Answer grid
        grid_h, grid_meta = answer_grid.draw(self.cfg.total_questions)
        self.metadata["blocks"]["questions"] = grid_meta

        # 7. Registration markers (ArUco) – placed absolutely, not part of flow
        marker_meta = marker.draw()
        self.metadata["blocks"]["registration_markers"] = marker_meta

        c.save()

        # Write JSON metadata
        with open(self.cfg.json_filename, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)

        print(f"Generated: {self.cfg.pdf_filename} and {self.cfg.json_filename}")