# -*- coding: utf-8 -*-
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from fastapi import BackgroundTasks
from app.services.exam_service import create_exam_job, run_exam_generation, ExamServiceError, delete_exam

from app import models, schemas
from app.database import get_db
from app.deps import require_teacher

router = APIRouter(prefix="/exams", tags=["exams"])


def _get_owned_exam(exam_id: str, user: models.User, db: Session) -> models.Exam:
    exam = db.get(models.Exam, exam_id)
    if not exam or exam.teacher_id != user.id:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi")
    return exam


@router.post("", response_model=schemas.ExamOut)
def create_exam_endpoint(
    payload: schemas.ExamCreateIn, background_tasks: BackgroundTasks,
    user: models.User = Depends(require_teacher), db: Session = Depends(get_db),
):
    try:
        exam, job = create_exam_job(
            db, teacher=user, group_id=payload.group_id, test_set_id=payload.test_set_id,
            paper_variant_count=payload.paper_variant_count, name=payload.name,  # YANGI
        )
    except ExamServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))

    background_tasks.add_task(run_exam_generation, exam.id, job.id, payload.paper_variant_count)
    return exam

@router.get("/{exam_id}/status")
def get_exam_status(exam_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    exam = _get_owned_exam(exam_id, user, db)
    job = (
        db.query(models.ProcessingJob)
        .filter(models.ProcessingJob.exam_id == exam.id)
        .order_by(models.ProcessingJob.created_at.desc())
        .first()
    )
    return {
        "exam_status": exam.status.value,
        "job_status": job.status.value if job else None,
        "progress": job.progress if job else None,
        "error": job.error_message if job else None,
    }

@router.get("", response_model=list[schemas.ExamOut])
def list_exams(user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    return (
        db.query(models.Exam)
        .filter(models.Exam.teacher_id == user.id)
        .order_by(models.Exam.created_at.desc())
        .all()
    )


@router.get("/{exam_id}", response_model=schemas.ExamOut)
def get_exam(exam_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    return _get_owned_exam(exam_id, user, db)

@router.patch("/{exam_id}/public-checking", response_model=schemas.ExamOut)
def toggle_public_checking(exam_id: str, enabled: bool,
                            user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    exam = _get_owned_exam(exam_id, user, db)
    exam.public_checking = enabled
    db.commit()
    db.refresh(exam)
    return exam

@router.get("/{exam_id}/students-with-results")
def get_exam_students_with_results(
    exam_id: str,
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db)
):
    """Imtihon uchun barcha o'quvchilar va ularning natijalarini (agar mavjud bo'lsa) qaytaradi."""
    exam = _get_owned_exam(exam_id, user, db)
    exam_students = db.query(models.ExamStudent).filter(
        models.ExamStudent.exam_id == exam.id
    ).all()
    
    result_list = []
    for es in exam_students:
        student = es.student
        result = es.result  # relationship orqali
        result_list.append({
            "student_id": student.id,
            "full_name": student.full_name,
            "booklet_id": es.booklet_id,
            "paper_variant_number": es.paper_variant_number,
            "has_result": result is not None,
            "result_id": result.id if result else None,
            "correct_count": result.correct_count if result else None,
            "incorrect_count": result.incorrect_count if result else None,
            "blank_count": result.blank_count if result else None,
            "ambiguous_count": result.ambiguous_count if result else None,
            "total_score": result.total_score if result else None,
            "status": result.status.value if result else None,
            "has_pdf": bool(result.result_pdf_path) if result else False,
        })
    
    return result_list



# exams.py dagi download_exam_zip funksiyasi
@router.get("/{exam_id}/download")
def download_exam_zip(exam_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    exam = _get_owned_exam(exam_id, user, db)
    if exam.status != models.ExamStatus.ready:
        raise HTTPException(status_code=400, detail="Imtihon hali tayyor emas")
    if not exam.zip_path or not Path(exam.zip_path).exists():
        # Agar fayl mavjud bo'lmasa, statusni failed ga o'zgartirib xatolik qaytaramiz
        exam.status = models.ExamStatus.failed
        db.commit()
        raise HTTPException(status_code=404, detail="Imtihon fayli topilmadi. Iltimos, qayta urinib ko'ring.")
    return FileResponse(exam.zip_path, media_type="application/zip", filename=f"{exam.exam_code}.zip")


@router.get("/{exam_id}/student/{student_id}/booklet")
def download_student_booklet(
    exam_id: str,
    student_id: str,
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db)
):
    """O'quvchining savollar kitobi (booklet) PDF ni yuklab olish."""
    exam = _get_owned_exam(exam_id, user, db)
    exam_student = db.query(models.ExamStudent).filter(
        models.ExamStudent.exam_id == exam.id,
        models.ExamStudent.student_id == student_id
    ).first()
    if not exam_student:
        raise HTTPException(status_code=404, detail="O'quvchi imtihonda topilmadi")
    if not exam_student.booklet_pdf_path or not Path(exam_student.booklet_pdf_path).exists():
        raise HTTPException(status_code=404, detail="Booklet PDF topilmadi")
    return FileResponse(
        exam_student.booklet_pdf_path,
        media_type="application/pdf",
        filename=f"booklet_{exam_student.booklet_id}.pdf"
    )


@router.get("/{exam_id}/student/{student_id}/answer-sheet")
def download_student_answer_sheet(
    exam_id: str,
    student_id: str,
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db)
):
    """O'quvchining javoblar varaqasi (answer sheet) PDF ni yuklab olish."""
    exam = _get_owned_exam(exam_id, user, db)
    exam_student = db.query(models.ExamStudent).filter(
        models.ExamStudent.exam_id == exam.id,
        models.ExamStudent.student_id == student_id
    ).first()
    if not exam_student:
        raise HTTPException(status_code=404, detail="O'quvchi imtihonda topilmadi")
    if not exam_student.answer_sheet_pdf_path or not Path(exam_student.answer_sheet_pdf_path).exists():
        raise HTTPException(status_code=404, detail="Javoblar varaqasi PDF topilmadi")
    return FileResponse(
        exam_student.answer_sheet_pdf_path,
        media_type="application/pdf",
        filename=f"answer_sheet_{exam_student.booklet_id}.pdf"
    )

@router.get("/{exam_student_id}/ambiguous-questions")
def get_ambiguous_questions(
    exam_student_id: str,
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """
    Berilgan ExamStudent uchun noaniq savollar ro'yxatini qaytaradi.
    """
    exam_student = db.get(models.ExamStudent, exam_student_id)
    if not exam_student:
        raise HTTPException(status_code=404, detail="ExamStudent topilmadi")
    
    if exam_student.exam.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    
    # Natija mavjud bo'lsa
    result = exam_student.result
    if not result:
        return {"ambiguous_questions": []}
    
    raw_answers = result.raw_answers_json or {}
    ambiguous_qs = [int(k) for k, v in raw_answers.items() if v == "MULTI"]
    
    return {
        "ambiguous_questions": sorted(ambiguous_qs),
        "total": len(ambiguous_qs),
        "student": exam_student.student.full_name,
        "exam_code": exam_student.exam.exam_code,
    }

@router.delete("/{exam_id}")
def delete_exam_endpoint(exam_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    exam = _get_owned_exam(exam_id, user, db)
    delete_exam(db, exam)
    return {"ok": True}