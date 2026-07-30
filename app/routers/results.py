# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import require_teacher
from app.security import decode_file_access_token

router = APIRouter(prefix="/results", tags=["results"])


def _get_owned_result(result_id: str, user: models.User, db: Session) -> models.Result:
    result = db.get(models.Result, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Natija topilmadi")
    teacher_id = result.exam_student.exam.teacher_id
    if teacher_id != user.id:
        raise HTTPException(status_code=404, detail="Natija topilmadi")
    return result


@router.get("/{result_id}")
def get_result(result_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    result = _get_owned_result(result_id, user, db)
    return {
        "id": result.id,
        "student": result.exam_student.student.full_name,
        "correct_count": result.correct_count,
        "incorrect_count": result.incorrect_count,
        "blank_count": result.blank_count,
        "ambiguous_count": result.ambiguous_count,
        "total_score": result.total_score,
        "per_subject": result.per_subject_json,
        "status": result.status,
        "has_pdf": bool(result.result_pdf_path),
    }


@router.get("/{result_id}/download")
def download_result_pdf(result_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Teacher o'z JWT tokeni bilan yuklab oladi (normal, autentifikatsiya
    talab qiladigan yo'l -- TZ 29-bo'lim: "Generated files public URL
    orqali ochilmasin")."""
    result = _get_owned_result(result_id, user, db)
    if not result.result_pdf_path:
        raise HTTPException(status_code=400, detail="Natija PDF hali tayyor emas")
    return FileResponse(result.result_pdf_path, media_type="application/pdf",
                         filename=f"natija_{result_id}.pdf")


@router.get("/{result_id}/public")
def download_result_pdf_public(result_id: str, token: str, db: Session = Depends(get_db)):
    """Natija PDF'ining O'ZIDAGI QR kodi shu endpointga ishora qiladi.
    Autentifikatsiya talab qilinmaydi, lekin `token` -- shu bitta
    result_id uchun yaratilgan, muddati tugaydigan imzolangan token
    (app.security.create_file_access_token). Token noto'g'ri, boshqa
    resursga tegishli yoki muddati tugagan bo'lsa -- rad etiladi. Shu
    tarzda fayl "doimiy ochiq URL" bo'lmaydi, lekin QR orqali ochish
    ishlaydi."""
    resource_id = decode_file_access_token(token)
    if not resource_id or resource_id != result_id:
        raise HTTPException(status_code=403, detail="Havola yaroqsiz yoki muddati tugagan")

    result = db.get(models.Result, result_id)
    if not result or not result.result_pdf_path:
        raise HTTPException(status_code=404, detail="Natija PDF topilmadi")

    return FileResponse(result.result_pdf_path, media_type="application/pdf",
                         filename=f"natija_{result_id}.pdf")