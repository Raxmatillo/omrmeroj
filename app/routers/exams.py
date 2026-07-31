# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from fastapi import BackgroundTasks
from app.services.exam_service import create_exam_job, run_exam_generation, ExamServiceError

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
            paper_variant_count=payload.paper_variant_count,
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


@router.get("/{exam_id}/download")
def download_exam_zip(exam_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """MUHIM: bu public URL emas -- faqat shu imtihon egasi bo'lgan
    teacher o'z JWT tokeni bilan yuklab olishi mumkin (TZ 29-bo'lim:
    "Generated files public URL orqali ochilmasin")."""
    exam = _get_owned_exam(exam_id, user, db)
    if exam.status != models.ExamStatus.ready or not exam.zip_path:
        raise HTTPException(status_code=400, detail="Imtihon hali tayyor emas")
    return FileResponse(exam.zip_path, media_type="application/zip", filename=f"{exam.exam_code}.zip")

