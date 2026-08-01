# -*- coding: utf-8 -*-
import shutil
from pathlib import Path
from sqlalchemy.orm import Session

from app import models
from app.config import settings


def delete_user_account(db: Session, user: models.User) -> None:
    """
    Foydalanuvchini va unga tegishli barcha ma'lumotlarni o'chiradi.
    """
    # 1. Guruhlar va ularning o'quvchilari
    groups = db.query(models.Group).filter(models.Group.teacher_id == user.id).all()
    for group in groups:
        for student in group.students:
            # Student bilan bog'liq ExamStudent va Result'lar kaskadli o'chadi
            pass
    
    # 2. TestSet, Variant, Question
    test_sets = db.query(models.TestSet).filter(models.TestSet.teacher_id == user.id).all()
    for ts in test_sets:
        for variant in ts.variants:
            # Savollar variant bilan birga o'chadi
            pass
    
    # 3. Imtihonlar va ularning fayllari
    exams = db.query(models.Exam).filter(models.Exam.teacher_id == user.id).all()
    for exam in exams:
        for es in exam.students:
            if es.result:
                if es.result.result_pdf_path:
                    Path(es.result.result_pdf_path).unlink(missing_ok=True)
                scan_path = Path(settings.OUTPUT_DIR) / "result_scans" / f"{es.result.id}.jpg"
                scan_path.unlink(missing_ok=True)
            if es.booklet_pdf_path:
                Path(es.booklet_pdf_path).unlink(missing_ok=True)
            if es.answer_sheet_pdf_path:
                Path(es.answer_sheet_pdf_path).unlink(missing_ok=True)
        if exam.zip_path:
            Path(exam.zip_path).unlink(missing_ok=True)
        exam_dir = Path(settings.OUTPUT_DIR) / exam.id
        shutil.rmtree(exam_dir, ignore_errors=True)
    
    # 4. Foydalanuvchini o'chirish (kaskadli o'chirish bilan bog'liq barcha yozuvlar o'chadi)
    db.delete(user)
    db.commit()