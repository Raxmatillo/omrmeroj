# config.py
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

@dataclass
class LayoutConfig:
    """All configurable dimensions and appearance settings."""
    # Page
    page_width_mm: float = 210.0
    page_height_mm: float = 297.0
    dpi: int = 300

    # Margins (mm)
    margin_top_mm: float = 12.0
    margin_bottom_mm: float = 12.0
    margin_left_mm: float = 15.0
    margin_right_mm: float = 15.0

    # Bubble geometry (mm)
    bubble_radius_mm: float = 3.0
    bubble_stroke_width_mm: float = 0.5
    bubble_gap_mm: float = 2.0          # horizontal gap between bubbles in a group
    row_height_mm: float = 8.0          # vertical distance between question rows
    column_width_mm: float = 28.0       # width reserved for one answer column (including locator, number, bubbles)

    # Answer options
    options: List[str] = field(default_factory=lambda: ['A', 'B', 'C', 'D'])  # can be extended to E

    # Locator marker (square side length)
    locator_size_mm: float = 2.5

    # Question column mapping
    question_columns: Dict[int, int] = field(default_factory=lambda: {
        30: 1,
        45: 2,
        60: 2,
        90: 3,
    })

    # Booklet ID
    booklet_digits: int = 7
    booklet_digit_gap_mm: float = 5.0  # horizontal gap between digit columns

    # Variant
    variant_gap_mm: float = 6.0  # gap between variant bubbles

    # ArUco marker size (mm) (square side including border)
    aruco_marker_size_mm: float = 10.0
    aruco_margin_mm: float = 5.0  # distance from page edge to marker center

    # Font sizes (pt)
    font_size_title: int = 18
    font_size_subtitle: int = 12
    font_size_normal: int = 10
    font_size_small: int = 8

    # File output
    pdf_filename: str = "answer_sheet.pdf"
    json_filename: str = "answer_sheet.layout.json"

    # Exam data
    exam_name: str = "2026-YIL KIRISH IMTIHONI"
    subjects: List[str] = field(default_factory=lambda: ["Matematika", "Ona tili", "Tarix", "Biologiya"])
    score_mode: str = "per_subject"  # "per_subject" or "overall"
    subject_scores: Optional[Dict[str, float]] = None  # if per_subject, e.g. {"Matematika":30, ...}
    overall_max_score: Optional[float] = None  # if overall mode
    total_questions: int = 90