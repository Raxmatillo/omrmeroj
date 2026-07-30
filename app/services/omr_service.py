# -*- coding: utf-8 -*-
"""
Javob varag'ini tekshirish integratsiyasi.

Bubble-aniqlash, perspective correction (4 ta registratsiya markeri
orqali) va QR o'qishning HAMMASI app/omr/omr_reader.py ichida (sizning
tayyor CV kodingiz) -- bu servis quyidagilarni bajaradi:

  1. Bot/API orqali kelgan fayl baytlarini vaqtinchalik faylga yozadi
     (omr_reader.detect_answer_sheet() fayl yo'lini kutadi).
  2. detect_answer_sheet() natijasini chaqiradi.
  3. QR kod ichidan booklet_id'ni ajratib oladi.
  4. booklet_id orqali DB'dan ExamStudent (source of truth answer key)
     topadi.
  5. Har bir savol uchun berilgan javobni to'g'ri javob bilan solishtirib,
     Result yozuvini yaratadi va saqlaydi.
  6. Tekislangan (warped) skan rasmini diskka saqlaydi va shu rasm +
     hisoblangan natija asosida NATIJA PDF generatsiya qiladi
     (TZ 19-bo'lim), so'ng Result.result_pdf_path'ni to'ldiradi.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import cv2
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.omr.omr_reader import detect_answer_sheet
from app.omr.result_pdf_generator import generate_result_pdf
from app.security import create_file_access_token

logger = logging.getLogger("omrmeroj.omr")


class OmrError(Exception):
    """Foydalanuvchiga to'g'ridan-to'g'ri ko'rsatsa bo'ladigan, kutilgan
    xatolar uchun (QR o'qilmadi, booklet topilmadi va h.k.)."""


def _parse_booklet_id(sheet_id_raw: str | None) -> str:
    """
    answer_sheet_generator.create_qr_image() QR ichiga JSON yozadi:
        {"exam_id": "...", "booklet_id": "..."}
    omr_reader.read_qr_code() bu matnni xomligicha qaytaradi -- shu yerda
    parse qilinadi. Agar biror sabab bilan QR ichida oddiy matn (faqat
    booklet_id) bo'lsa, shuni ham qabul qilamiz (orqaga moslik uchun).
    """
    if not sheet_id_raw:
        raise OmrError("QR kod topilmadi -- rasm sifatini tekshiring yoki qayta suratga oling")

    try:
        payload = json.loads(sheet_id_raw)
        booklet_id = str(payload["booklet_id"]).strip()
    except (json.JSONDecodeError, KeyError, TypeError):
        booklet_id = sheet_id_raw.strip()

    if not booklet_id:
        raise OmrError("QR kod ichidan booklet_id o'qib bo'lmadi")
    return booklet_id


def _save_scanned_preview(warped_image, result_id: str) -> str:
    """Natija PDF ichida rasm ekranda hech qachon ~105mm dan katta
    ko'rsatilmaydi -- shuning uchun to'liq 300dpi (~2480x3508px) PNG
    saqlash faqat fayl hajmini shishiradi (5-8 MB). Shu sababli: eni
    max 1400px gacha kichraytiriladi va PNG o'rniga JPEG (sifat=82)
    formatida saqlanadi -- ko'zga sezilarli sifat yo'qotmasdan
    5-10 marta kichikroq fayl beradi."""
    out_dir = Path(settings.OUTPUT_DIR) / "result_scans"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result_id}.jpg"

    preview = warped_image
    max_width_px = 1400
    h, w = preview.shape[:2]
    if w > max_width_px:
        scale = max_width_px / w
        preview = cv2.resize(preview, (max_width_px, int(h * scale)), interpolation=cv2.INTER_AREA)

    cv2.imwrite(str(path), preview, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return str(path)


def _build_download_url(result_id: str) -> str:
    """Natija PDF QR kodiga qo'yiladigan, muddati tugaydigan (signed)
    havola. TZ 29-bo'lim: "Generated files public URL orqali ochilmasin"
    -- shuning uchun doimiy ochiq URL emas, token asosidagi vaqtinchalik
    havola beriladi. Frontend/base URL hozircha settings orqali sozlanadi
    emas -- shuning uchun nisbiy yo'l qaytariladi; deploy muhitida buni
    to'liq domenga ulash kerak bo'ladi (masalan settings.PUBLIC_BASE_URL)."""
    token = create_file_access_token(result_id)
    base_url = getattr(settings, "PUBLIC_BASE_URL", "") or ""
    return f"{base_url}/results/{result_id}/public?token={token}"


def check_answer_sheet(db: Session, file_bytes: bytes, filename_hint: str = "sheet.pdf") -> models.Result:
    """
    file_bytes    -- bot/API orqali kelgan PDF yoki rasm baytlari.
    filename_hint -- asl fayl nomi (yoki kengaytmani bildiruvchi nom,
                     masalan "sheet.jpg"); omr_reader.load_image()
                     kengaytmaga qarab PDF/rasm yuklash yo'lini tanlaydi.
    """
    suffix = os.path.splitext(filename_hint)[-1].lower() or ".pdf"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        try:
            report = detect_answer_sheet(tmp_path)
        except Exception as e:  # noqa: BLE001 -- omr_reader turli xil CV/format xatolarini beradi
            logger.exception("omr_reader.detect_answer_sheet xato berdi")
            raise OmrError(f"Javob varag'ini o'qib bo'lmadi: {e}") from e
    finally:
        os.unlink(tmp_path)

    booklet_id = _parse_booklet_id(report.get("sheet_id"))

    exam_student = (
        db.query(models.ExamStudent)
        .filter(models.ExamStudent.booklet_id == booklet_id)
        .first()
    )
    if not exam_student:
        raise OmrError(f"Booklet ID topilmadi: {booklet_id}")
        # YANGI KOD:
    if exam_student.result is not None:
        db.delete(exam_student.result)
        db.flush()

    # generate_question_booklet.build() / randomization.build_shuffled_booklet()
    # answer_key_json'ni shu formatda yozadi:
    #   {tartib: {"fan": ..., "ball": ..., "correct_letter_shown_to_student": "B", ...}}
    answer_key: dict = exam_student.answer_key_json

    raw_answers: dict[str, str | None] = {}
    for q in report["questions"]:
        key = str(q.question)
        if q.status == "blank":
            raw_answers[key] = None
        elif q.status == "uncertain":
            raw_answers[key] = "MULTI"
        else:
            raw_answers[key] = q.answer

    # YANGI: TEST VARIANTI tekshiruvi. exam_student.paper_variant_number
    # None bo'lsa (bu imtihonda variant ishlatilmagan) -- tekshirilmaydi.
    detected_variant = report.get("detected_paper_variant")
    variant_status = report.get("paper_variant_status")
    expected_variant = exam_student.paper_variant_number


    # YANGI
    variant_mismatch = False
    if expected_variant is not None:
        # Faqat RAQAM boshqacha chiqsa yoki umuman belgilanmagan bo'lsa --
        # "boshqa talaba varag'i" degan jiddiy ogohlantirish beriladi.
        # Raqam to'g'ri topilgan bo'lsa, bo'yash biroz noaniq bo'lsa ham
        # bu mismatch emas (chalkash xabar bermaslik uchun).
        variant_mismatch = (detected_variant is None) or (detected_variant != expected_variant)
        

    correct = incorrect = blank = ambiguous = 0

    per_subject: dict[str, dict] = {}
    total_score = 0.0

    for tartib_str, meta in answer_key.items():
        given = raw_answers.get(tartib_str)
        correct_letter = meta["correct_letter_shown_to_student"]
        ball = float(meta.get("ball", 1))
        fan = meta.get("fan", "Umumiy")

        subj = per_subject.setdefault(fan, {"correct": 0, "total": 0, "score": 0.0})
        subj["total"] += 1

        if given is None:
            blank += 1
        elif given == "MULTI":
            ambiguous += 1
        elif given == correct_letter:
            correct += 1
            total_score += ball
            subj["correct"] += 1
            subj["score"] += ball
        else:
            incorrect += 1

    status = (
        models.ResultStatus.needs_review
        if (ambiguous > 0 or variant_mismatch)
        else models.ResultStatus.ok
    )

    result = models.Result(
        exam_student_id=exam_student.id,
        raw_answers_json=raw_answers,
        correct_count=correct,
        incorrect_count=incorrect,
        blank_count=blank,
        ambiguous_count=ambiguous,
        total_score=total_score,
        per_subject_json=per_subject,
        detected_paper_variant=detected_variant,   # YANGI
        variant_mismatch=variant_mismatch,         # YANGI
        status=status,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    # --- Natija PDF (TZ 19-bo'lim) ---
    # Bu bosqich "best-effort": agar biror sababdan PDF yaratib bo'lmasa
    # (masalan shrift/QR kutubxonasi bilan bog'liq muvaqqat xato), natija
    # o'zi (Result yozuvi) baribir saqlanган bo'lib qoladi -- foydalanuvchi
    # keyin qayta generatsiya qilishni so'rashi mumkin bo'ladi.
    try:
        student = exam_student.student
        group_name = student.group.name if student.group else ""
        exam = exam_student.exam

        scanned_path = _save_scanned_preview(report["warped_image"], result.id)
        download_url = _build_download_url(result.id)

        exam_name = ""
        if exam_student.variant and exam_student.variant.test_set:
            exam_name = exam_student.variant.test_set.name

        variant_label = exam_student.variant.label if exam_student.variant else None   # <-- YANGI

        pdf_path = Path(settings.OUTPUT_DIR) / "results" / f"{result.id}.pdf"
        generate_result_pdf(
            output_path=str(pdf_path),
            student_full_name=student.full_name,
            group_name=group_name,
            exam_name=exam_name,
            exam_code=exam.exam_code if exam else "",
            total_score=total_score,
            total_questions=exam.total_questions if exam else len(answer_key),
            raw_answers=raw_answers,
            answer_key=answer_key,
            per_subject=per_subject,
            scanned_image_path=scanned_path,
            download_url=download_url,
            variant_label=variant_label,   # <-- YANGI
        )
        result.result_pdf_path = str(pdf_path)
        db.commit()
        db.refresh(result)
    except Exception:  # noqa: BLE001
        logger.exception("Natija PDF generatsiyasida xato -- Result baribir saqlandi")

    return result

def apply_manual_corrections(db: Session, result: models.Result, corrections: dict[str, str | None]) -> models.Result:
    """
    corrections -- {"15": "A", "24": None, ...}: savol raqami (string) ->
    o'qituvchi qo'lda kiritgan to'g'ri harf ("A"/"B"/"C"/"D"), yoki None
    (talaba hech narsa belgilamagan / o'qib bo'lmadi deb hisoblansin).

    Bu funksiya faqat MULTI (noaniq) deb belgilangan savollarni tuzatish
    uchun mo'ljallangan, lekin o'zi buni majburlamaydi -- qaysi savollar
    noaniq ekanligini chaqiruvchi (bot/handler) tomonda tekshiring.
    """
    exam_student = result.exam_student
    answer_key: dict = exam_student.answer_key_json

    raw_answers = dict(result.raw_answers_json or {})
    raw_answers.update(corrections)

    correct = incorrect = blank = ambiguous = 0
    per_subject: dict[str, dict] = {}
    total_score = 0.0

    for tartib_str, meta in answer_key.items():
        given = raw_answers.get(tartib_str)
        correct_letter = meta["correct_letter_shown_to_student"]
        ball = float(meta.get("ball", 1))
        fan = meta.get("fan", "Umumiy")

        subj = per_subject.setdefault(fan, {"correct": 0, "total": 0, "score": 0.0})
        subj["total"] += 1

        if given is None:
            blank += 1
        elif given == "MULTI":
            ambiguous += 1
        elif given == correct_letter:
            correct += 1
            total_score += ball
            subj["correct"] += 1
            subj["score"] += ball
        else:
            incorrect += 1

    result.raw_answers_json = raw_answers
    result.correct_count = correct
    result.incorrect_count = incorrect
    result.blank_count = blank
    result.ambiguous_count = ambiguous
    result.total_score = total_score
    result.per_subject_json = per_subject
    result.status = (
        models.ResultStatus.needs_review
        if (ambiguous > 0 or result.variant_mismatch)
        else models.ResultStatus.ok
    )
    db.commit()
    db.refresh(result)

    # Natija PDF'ni yangilangan javoblar bilan qayta generatsiya qilamiz
    try:
        student = exam_student.student
        group_name = student.group.name if student.group else ""
        exam = exam_student.exam
        variant_label = exam_student.variant.label if exam_student.variant else None

        scanned_path = None
        candidate = Path(settings.OUTPUT_DIR) / "result_scans" / f"{result.id}.jpg"
        if candidate.exists():
            scanned_path = str(candidate)

        download_url = _build_download_url(result.id)
        exam_name = ""
        if exam_student.variant and exam_student.variant.test_set:
            exam_name = exam_student.variant.test_set.name

        pdf_path = Path(settings.OUTPUT_DIR) / "results" / f"{result.id}.pdf"
        generate_result_pdf(
            output_path=str(pdf_path),
            student_full_name=student.full_name,
            group_name=group_name,
            exam_name=exam_name,
            exam_code=exam.exam_code if exam else "",
            total_score=total_score,
            total_questions=exam.total_questions if exam else len(answer_key),
            raw_answers=raw_answers,
            answer_key=answer_key,
            per_subject=per_subject,
            scanned_image_path=scanned_path,
            download_url=download_url,
            variant_label=variant_label,
        )
        result.result_pdf_path = str(pdf_path)
        db.commit()
        db.refresh(result)
    except Exception:  # noqa: BLE001
        logger.exception("Qo'lda tuzatishdan keyin natija PDF qayta generatsiyasida xato")

    return result