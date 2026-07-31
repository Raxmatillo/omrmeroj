# -*- coding: utf-8 -*-
from io import BytesIO
from openpyxl import Workbook
from sqlalchemy.orm import Session
from app import models


def export_teacher_results_excel(db: Session, teacher_id: str) -> BytesIO:
    wb = Workbook()

    ws = wb.active
    ws.title = "Natijalar"
    ws.append([
        "O'qituvchi", "Guruh", "Test", "O'quvchi", "Variant", "Booklet ID",
        "To'g'ri", "Noto'g'ri", "Bo'sh", "Noaniq", "Umumiy ball", "Holat", "Sana",
    ])

    ws2 = wb.create_sheet("Fanlar bo'yicha")
    ws2.append(["O'quvchi", "Guruh", "Test", "Fan", "To'g'ri", "Jami savol", "Ball"])

    results = (
        db.query(models.Result)
        .join(models.ExamStudent)
        .join(models.Exam)
        .filter(models.Exam.teacher_id == teacher_id)
        .all()
    )

    for r in results:
        es = r.exam_student
        student = es.student
        group_name = student.group.name if student.group else ""
        test_name = es.exam.test_set.name if es.exam.test_set else ""
        variant_label = es.variant.label if es.variant else ""
        teacher_name = es.exam.teacher.full_name or es.exam.teacher.phone

        ws.append([
            teacher_name, group_name, test_name, student.full_name, variant_label,
            es.booklet_id, r.correct_count, r.incorrect_count, r.blank_count,
            r.ambiguous_count, r.total_score, r.status.value,
            r.checked_at.strftime("%Y-%m-%d %H:%M") if r.checked_at else "",
        ])

        for fan, s in (r.per_subject_json or {}).items():
            ws2.append([student.full_name, group_name, test_name, fan,
                        s.get("correct", 0), s.get("total", 0), s.get("score", 0)])

    for sheet in (ws, ws2):
        for col in sheet.columns:
            width = max(len(str(c.value or "")) for c in col) + 2
            sheet.column_dimensions[col[0].column_letter].width = min(width, 40)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf