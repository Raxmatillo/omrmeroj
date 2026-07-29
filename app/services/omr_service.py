# -*- coding: utf-8 -*-
"""
Javob varag'ini tekshirish integratsiyasi.

Bubble-aniqlash, perspective correction (4 ta registratsiya markeri
orqali) va QR o'qishning HAMMASI app/omr/omr_reader.py ichida (sizning
tayyor CV kodingiz) -- bu servis faqat quyidagilarni bajaradi:

  1. Bot orqali kelgan fayl baytlarini vaqtinchalik faylga yozadi
     (omr_reader.detect_answer_sheet() fayl yo'lini kutadi).
  2. detect_answer_sheet() natijasini chaqiradi.
  3. QR kod ichidan (answer_sheet_generator.py JSON formatida yozadi:
     {"exam_id": ..., "booklet_id": ...}) booklet_id'ni ajratib oladi.
  4. booklet_id orqali DB'dan ExamStudent (demak -- answer_key_json,
     "source of truth" javob kaliti) topadi.
  5. Har bir savol uchun berilgan javobni to'g'ri javob bilan solishtirib,
     Result yozuvini yaratadi va saqlaydi.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from sqlalchemy.orm import Session

from app import models
from app.omr.omr_reader import detect_answer_sheet

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


def check_answer_sheet(db: Session, file_bytes: bytes, filename_hint: str = "sheet.pdf") -> models.Result:
    """
    file_bytes    -- bot orqali kelgan PDF yoki rasm baytlari.
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
    if exam_student.result is not None:
        raise OmrError("Bu javob varag'i allaqachon tekshirilgan")

    # generate_question_booklet.build() answer_key_json'ni shu formatda yozadi:
    #   {tartib: {"fan": ..., "ball": ..., "correct_letter_shown_to_student": "B",
    #             "letter_to_original_option": {...}}}
    answer_key: dict = exam_student.answer_key_json

    raw_answers: dict[int, str | None] = {}
    for q in report["questions"]:
        if q.status == "blank":
            raw_answers[q.question] = None
        elif q.status == "uncertain":
            raw_answers[q.question] = "MULTI"
        else:  # "marked"
            raw_answers[q.question] = q.answer

    correct = incorrect = blank = ambiguous = 0
    per_subject: dict[str, dict[str, float]] = {}
    total_score = 0.0

    for tartib_str, meta in answer_key.items():
        tartib = int(tartib_str)
        given = raw_answers.get(tartib)
        correct_letter = meta["correct_letter_shown_to_student"]
        ball = float(meta.get("ball", 1))
        fan = meta.get("fan", "Umumiy")

        subj = per_subject.setdefault(fan, {"correct": 0, "total": 0})
        subj["total"] += 1

        if given is None:
            blank += 1
        elif given == "MULTI":
            ambiguous += 1
        elif given == correct_letter:
            correct += 1
            total_score += ball
            subj["correct"] += 1
        else:
            incorrect += 1

    status = models.ResultStatus.needs_review if ambiguous > 0 else models.ResultStatus.ok

    result = models.Result(
        exam_student_id=exam_student.id,
        raw_answers_json={str(k): v for k, v in raw_answers.items()},
        correct_count=correct,
        incorrect_count=incorrect,
        blank_count=blank,
        ambiguous_count=ambiguous,
        total_score=total_score,
        per_subject_json=per_subject,
        status=status,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result
