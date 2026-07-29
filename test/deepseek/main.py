# main.py
from config import LayoutConfig
from generator import AnswerSheetGenerator

if __name__ == "__main__":
    # Example configuration
    config = LayoutConfig(
        exam_name="2026-YIL KIRISH IMTIHONI",
        subjects=["Matematika", "Ona tili", "Tarix", "Biologiya"],
        score_mode="per_subject",
        subject_scores={"Matematika": 30, "Ona tili": 20, "Tarix": 25, "Biologiya": 25},
        total_questions=90,
        bubble_radius_mm=2.8,        # slightly smaller to fit
        row_height_mm=7.5,
        column_width_mm=30,
        options=['A', 'B', 'C', 'D'],  # default 4, extend to ['A','B','C','D','E'] if needed
    )
    gen = AnswerSheetGenerator(config)
    gen.generate()