# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import require_teacher
from app.services.exam_service import create_exam, ExamServiceError

router = APIRouter(prefix="/exams", tags=["exams"])


def _get_owned_exam(exam_id: str, user: models.User, db: Session) -> models.Exam:
    exam = db.get(models.Exam, exam_id)
    if not exam or exam.teacher_id != user.id:
        raise HTTPException(status_code=404, detail="Imtihon topilmadi")
    return exam


@router.post("", response_model=schemas.ExamOut)
def create_exam_endpoint(payload: schemas.ExamCreateIn, user: models.User = Depends(require_teacher),
                          db: Session = Depends(get_db)):
    try:
        return create_exam(db, teacher=user, group_id=payload.group_id, test_set_id=payload.test_set_id)
    except ExamServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@router.get("/{exam_id}/download")
def download_exam_zip(exam_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """MUHIM: bu public URL emas -- faqat shu imtihon egasi bo'lgan
    teacher o'z JWT tokeni bilan yuklab olishi mumkin (TZ 29-bo'lim:
    "Generated files public URL orqali ochilmasin")."""
    exam = _get_owned_exam(exam_id, user, db)
    if exam.status != models.ExamStatus.ready or not exam.zip_path:
        raise HTTPException(status_code=400, detail="Imtihon hali tayyor emas")
    return FileResponse(exam.zip_path, media_type="application/zip", filename=f"{exam.exam_code}.zip")