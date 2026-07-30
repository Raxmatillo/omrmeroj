# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import require_teacher
from app.security import decode_file_access_token
from app.services.omr_service import check_answer_sheet, OmrError

router = APIRouter(prefix="/results", tags=["results"])


def _get_owned_result(result_id: str, user: models.User, db: Session) -> models.Result:
    result = db.get(models.Result, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Natija topilmadi")
    teacher_id = result.exam_student.exam.teacher_id
    if teacher_id != user.id:
        raise HTTPException(status_code=404, detail="Natija topilmadi")
    return result


@router.post("/check")
async def check_answer_sheet_endpoint(
    file: UploadFile = File(...),
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """
    Javoblar varag'ini (PDF yoki rasm: jpg/png/webp) yuklab tekshiradi --
    xuddi Telegram bot qilgani kabi (bot/handlers/omr.py), lekin
    saytdan/admin paneldan.

    Oqim (app/services/omr_service.py -- check_answer_sheet):
      1. Fayl baytlari vaqtinchalik faylga yoziladi va
         app/omr/omr_reader.py -> detect_answer_sheet() chaqiriladi
         (bubble aniqlash, perspective correction, QR o'qish).
      2. QR kod ichidan booklet_id ajratib olinadi.
      3. booklet_id orqali DB'dan ExamStudent (source of truth answer
         key -- ExamStudent.answer_key_json) topiladi.
      4. Har bir savol uchun berilgan javob to'g'ri javob bilan
         solishtiriladi, Result yozuvi yaratiladi va saqlanadi.
      5. Natija PDF (app/omr/result_pdf_generator.py -> generate_result_pdf)
         generatsiya qilinadi, Result.result_pdf_path to'ldiriladi.

    MUHIM (ownership): check_answer_sheet booklet_id orqali ExamStudent'ni
    topib oladi -- lekin bu ExamStudent boshqa teacherga tegishli
    imtihonga tegishli bo'lishi mumkin. Shuning uchun natija yaratilgach,
    uning imtihon egasi so'rov yuborgan teacher ekanligi ALOHIDA
    tekshiriladi (aks holda bir teacher boshqa teacherning javob
    varag'ini "tasodifan" tekshirib qo'yishi mumkin edi).
    """
    content = await file.read()

    try:
        result = check_answer_sheet(db, content, filename_hint=file.filename or "sheet.pdf")
    except OmrError as e:
        raise HTTPException(status_code=400, detail=str(e))

    teacher_id = result.exam_student.exam.teacher_id
    if teacher_id != user.id:
        # Natija allaqachon DB'da saqlangan (boshqa teacherning booklet'i
        # bo'lgani uchun) -- lekin so'rov yuborgan teacherga uni
        # ko'rsatmaymiz. O'chirib tashlamaymiz, chunki haqiqiy javob
        # varag'i haqiqatan ham tekshirilgan va uning egasi keyinchalik
        # o'zi ko'radi.
        raise HTTPException(
            status_code=403,
            detail="Bu javob varag'i boshqa teacherning imtihoniga tegishli",
        )

    return {
        "result_id": result.id,
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