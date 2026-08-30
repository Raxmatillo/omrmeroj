# -*- coding: utf-8 -*-
from pathlib import Path

from app.config import settings

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db, SessionLocal
from app.deps import require_teacher
from app.security import decode_file_access_token
from app.services.omr_service import check_answer_sheet, OmrError, OmrPermissionError, apply_manual_corrections

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
    Javoblar varag'ini (PDF yoki rasm) yuklab, DURABLE (server qayta
    ishga tushsa ham yo'qolmaydigan) tarzda navbatga qo'yadi.

    YANGILANISH: avval fayl faqat XOTIRADA (bytes) saqlanib,
    BackgroundTasks orqali ishlanardi -- server o'sha payt qulasa,
    fayl ham, ish ham butunlay yo'qolardi. Endi fayl DARHOL DISKKA
    yoziladi, va ish ProcessingJob sifatida DB'ga yoziladi --
    app/services/job_worker.py buni orqada avtomatik topib bajaradi,
    server qulab qayta ishga tushsa ham xuddi shu fayldan davom etadi.
    """
    content = await file.read()

    ext = Path(file.filename or "sheet.pdf").suffix or ".pdf"
    uploads_dir = Path(settings.OUTPUT_DIR) / "pending_checks"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    job = models.ProcessingJob(kind="omr_check", status=models.JobStatus.queued)
    db.add(job)
    db.flush()  # job.id kerak, hali commit qilinmagan

    file_path = uploads_dir / f"{job.id}{ext}"
    file_path.write_bytes(content)

    job.payload_json = {
        "file_path": str(file_path),
        "filename": file.filename or "sheet.pdf",
        "teacher_id": user.id,
    }
    db.commit()
    db.refresh(job)

    return {
        "status": "queued",
        # MUHIM: frontend (resultService.ts) shu "task_id" nomini kutadi --
        # ichki mazmuni endi ProcessingJob.id, lekin API kontrakti (maydon
        # nomi) o'zgartirilmadi, frontend'ga tegish shart emas.
        "task_id": job.id,
        "message": "Natija tayyorlanmoqda. Iltimos, birozdan keyin natijani tekshiring.",
        "check_url": f"/results/check-status/{job.id}",
    }


@router.get("/check-status/{task_id}")
def get_check_status(
    task_id: str,
    user: models.User = Depends(require_teacher),
):
    """
    Ish holatini DB'dan (ProcessingJob) o'qiydi -- endi xotiradagi
    vaqtinchalik dict (`pending_results`) emas, shuning uchun server
    qayta ishga tushsa ham holat YO'QOLMAYDI.
    """
    db = SessionLocal()
    try:
        job = db.get(models.ProcessingJob, task_id)
        if not job or job.kind != "omr_check":
            raise HTTPException(status_code=404, detail="Task topilmadi yoki muddati o'tgan")

        # Egalik tekshiruvi -- faqat so'rovni yuborgan teacher ko'ra oladi
        owner_id = (job.payload_json or {}).get("teacher_id")
        if owner_id and owner_id != user.id:
            raise HTTPException(status_code=404, detail="Task topilmadi")

        if job.status == models.JobStatus.completed:
            return {"status": "completed", "result": job.result_json}
        elif job.status == models.JobStatus.failed:
            return {"status": "failed", "error": job.error_message or "Noma'lum xatolik"}
        else:
            return {
                "status": "processing" if job.status == models.JobStatus.processing else "queued",
                "progress": job.progress or 0,
                "message": "Natija tayyorlanmoqda...",
            }
    finally:
        db.close()

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

# app/routers/results.py

def _build_result_detail(result: models.Result) -> schemas.ResultDetailOut:
    exam_student = result.exam_student
    answer_key = exam_student.answer_key_json
    raw_answers = result.raw_answers_json or {}

    questions: list[schemas.QuestionAnswerDetail] = []
    for tartib_str, meta in sorted(answer_key.items(), key=lambda kv: int(kv[0])):
        given = raw_answers.get(tartib_str)
        correct_letter = meta["correct_letter_shown_to_student"]

        if given is None:
            status = "blank"
        elif given == "MULTI":
            status = "ambiguous"
        elif given == correct_letter:
            status = "correct"
        else:
            status = "incorrect"

        questions.append(schemas.QuestionAnswerDetail(
            question=int(tartib_str),
            fan=meta.get("fan", ""),
            ball=float(meta.get("ball", 1)),
            given=None if given == "MULTI" else given,
            correct_letter=correct_letter,
            status=status,
            savol_html=meta.get("savol_html"),  # qo'shildi
            variant_a_html=meta.get("variant_a_html"),  # qo'shildi
            variant_b_html=meta.get("variant_b_html"),  # qo'shildi
            variant_c_html=meta.get("variant_c_html"),  # qo'shildi
            variant_d_html=meta.get("variant_d_html"),  # qo'shildi
        ))

    return schemas.ResultDetailOut(
        id=result.id,
        student=exam_student.student.full_name,
        correct_count=result.correct_count,
        incorrect_count=result.incorrect_count,
        blank_count=result.blank_count,
        ambiguous_count=result.ambiguous_count,
        total_score=result.total_score,
        per_subject=result.per_subject_json,
        status=result.status,
        has_pdf=bool(result.result_pdf_path),
        variant_mismatch=result.variant_mismatch,
        detected_paper_variant=result.detected_paper_variant,
        expected_paper_variant=exam_student.paper_variant_number,
        questions=questions,
    )

@router.get("/{result_id}/detail", response_model=schemas.ResultDetailOut)
def get_result_detail(result_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Admin panel uchun: har bir savolning holati (to'g'ri/xato/bo'sh/noaniq)
    alohida-alohida qaytariladi -- frontend shu asosida jadval chizib,
    noaniq (ambiguous) savollarni ajratib ko'rsatishi va tuzatish formasini
    chiqarishi mumkin."""
    result = _get_owned_result(result_id, user, db)
    return _build_result_detail(result)


@router.post("/{result_id}/manual-correction", response_model=schemas.ResultDetailOut)
def manual_correction_endpoint(
    result_id: str,
    payload: schemas.ManualCorrectionIn,
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """O'qituvchi admin paneldan (yoki botdagi kabi) noaniq -- yoki istalgan --
    savolni qo'lda tuzatadi. Faqat noaniq savollar bilan cheklanmaydi:
    o'qituvchi biror savolni xato o'qilgan deb hisoblasa, uni ham
    tuzatishi mumkin."""
    result = _get_owned_result(result_id, user, db)
    exam_student = result.exam_student
    answer_key = exam_student.answer_key_json

    invalid_questions = [q for q in payload.corrections if q not in answer_key]
    if invalid_questions:
        raise HTTPException(status_code=400, detail=f"Noma'lum savol raqamlari: {invalid_questions}")

    for letter in payload.corrections.values():
        if letter is not None and letter.upper() not in ("A", "B", "C", "D"):
            raise HTTPException(status_code=400, detail=f"Javob faqat A/B/C/D yoki bo'sh bo'lishi kerak: {letter!r}")

    normalized = {k: (v.upper() if v else None) for k, v in payload.corrections.items()}
    result = apply_manual_corrections(db, result, normalized)

    return _build_result_detail(result)



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

@router.delete("/{result_id}")
def delete_result(result_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    result = _get_owned_result(result_id, user, db)
    if result.result_pdf_path:
        Path(result.result_pdf_path).unlink(missing_ok=True)
    (Path(settings.OUTPUT_DIR) / "result_scans" / f"{result.id}.jpg").unlink(missing_ok=True)
    db.delete(result)
    db.commit()
    return {"ok": True}