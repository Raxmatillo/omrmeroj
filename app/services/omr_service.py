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

YANGILANISH (fan+ball takrorlanish bugini tuzatish):
  per_subject statistikasi endi answer_key'dagi "fan_group" maydoni
  bo'yicha guruhlanadi ("fan" emas). Bu -- bir xil fan nomi (masalan
  "Matematika") turli ball guruhida (masalan majburiy fanlar ichida
  1.1 ball va asosiy fan sifatida 3.1 ball) alohida-alohida qatorlarda
  ko'rsatilishini ta'minlaydi, aks holda ular bitta "Matematika"ga
  birlashib, natija noto'g'ri chiqardi.

  Orqaga moslik: agar answer_key eski (fan_group maydoni yo'q) bo'lsa,
  oddiy "fan" ishlatiladi -- eski imtihonlar ustida ishlash davom etadi.
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


def _subject_group_label(meta: dict) -> str:
    """answer_key ichidagi bitta savol meta'sidan natija statistikasi
    uchun ishlatiladigan guruh nomini oladi. "fan_group" bo'lsa shuni,
    bo'lmasa (eski imtihonlar uchun orqaga moslik) oddiy "fan"ni
    qaytaradi."""
    return meta.get("fan_group") or meta.get("fan", "Umumiy")


class OmrError(Exception):
    """Foydalanuvchiga to'g'ridan-to'g'ri ko'rsatsa bo'ladigan, kutilgan
    xatolar uchun (QR o'qilmadi, booklet topilmadi va h.k.)."""


class OmrPermissionError(OmrError):
    """Booklet boshqa teacherning imtihoniga tegishli bo'lganda ko'tariladi.
    Bu tekshiruv ExamStudent topilgandan KEYIN, lekin mavjud Result
    o'chirilishidan OLDIN bajarilishi SHART -- aks holda so'ragan teacher
    ruxsatga ega bo'lmasa ham, boshqa teacherning allaqachon saqlangan
    natijasi o'chirib yuborilgan bo'lardi."""


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


def check_answer_sheet(
    db: Session,
    file_bytes: bytes,
    filename_hint: str = "sheet.pdf",
    requester_teacher_id: str | None = None,
) -> models.Result:
    """
    file_bytes    -- bot/API orqali kelgan PDF yoki rasm baytlari.
    filename_hint -- asl fayl nomi (yoki kengaytmani bildiruvchi nom,
                     masalan "sheet.jpg"); omr_reader.load_image()
                     kengaytmaga qarab PDF/rasm yuklash yo'lini tanlaydi.
    requester_teacher_id -- so'rovni yuborayotgan teacher.id. Berilgan
                     bo'lsa, ExamStudent topilgandan keyin -- lekin
                     mavjud Result o'chirilishidan OLDIN -- egalik
                     tekshiriladi (OmrPermissionError). None bo'lsa
                     (masalan bot orqali public_checking oqimi uchun)
                     tekshiruv o'tkazib yuboriladi -- ownership'ni
                     chaqiruvchi o'zi boshqacha yo'l bilan hal qiladi.
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

    if requester_teacher_id is not None and exam_student.exam.teacher_id != requester_teacher_id:
        raise OmrPermissionError("Bu javob varag'i boshqa teacherning imtihoniga tegishli")

    if exam_student.result is not None:
        db.delete(exam_student.result)
        db.flush()

    # generate_question_booklet.build() / randomization.build_shuffled_booklet()
    # answer_key_json'ni shu formatda yozadi:
    #   {tartib: {"fan": ..., "fan_group": ..., "ball": ...,
    #             "correct_letter_shown_to_student": "B", ...}}
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
        fan = _subject_group_label(meta)  # YANGI: fan_group bo'yicha guruhlash

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

    # YANGI (Savollar banki): Toplam-asosidagi imtihon bo'lsa,
    # QuestionBankItem qiyinchilik statistikasini yangilaymiz.
    if exam_student.exam and exam_student.exam.toplam_id:
        try:
            from app.services.bank_service import sync_attempts_for_exam_student
            sync_attempts_for_exam_student(db, exam_student, raw_answers)
        except Exception:  # noqa: BLE001
            logger.exception("Savollar banki statistikasini yangilashda xato -- Result baribir saqlandi")

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
        elif exam and exam.toplam:  # YANGI: Toplam-asosidagi imtihonlarda variant yo'q
            exam_name = exam.toplam.name

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
            # YANGI: allaqachon hisoblangan statistikani to'g'ridan-to'g'ri
            # uzatamiz -- generate_result_pdf ichida qayta hisoblash shart
            # emas (bir xil ma'lumotni ikki marta sanamaslik uchun).
            correct_count=correct, incorrect_count=incorrect,
            blank_count=blank, ambiguous_count=ambiguous,
            checked_at=result.checked_at,
        )
        result.result_pdf_path = str(pdf_path)
        db.commit()
        db.refresh(result)
    except Exception:  # noqa: BLE001
        logger.exception("Natija PDF generatsiyasida xato -- Result baribir saqlandi")

    return result

# app/services/omr_service.py -- QO'SHIMCHA funksiyalar
def analyze_answer_sheet(file_bytes: bytes, filename_hint: str = "sheet.pdf") -> dict:
    """Faqat CV tahlili -- DB'ga hech narsa yozmaydi."""
    suffix = os.path.splitext(filename_hint)[-1].lower() or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        try:
            report = detect_answer_sheet(tmp_path)
        except Exception as e:
            raise OmrError(f"Javob varag'ini o'qib bo'lmadi: {e}") from e
    finally:
        os.unlink(tmp_path)
    return {"report": report, "booklet_id": _parse_booklet_id(report.get("sheet_id"))}


def _score_from_raw_answers(
    answer_key: dict, raw_answers: dict, detected_variant, variant_mismatch: bool
) -> dict:
    """raw_answers asosida ballarni hisoblaydi -- DB bilan ishlamaydi,
    shuning uchun ham dastlabki hisoblashda, ham qo'lda tuzatishdan
    keyin qayta hisoblashda ishlatiladi."""
    correct = incorrect = blank = ambiguous = 0
    per_subject: dict = {}
    total_score = 0.0

    for tartib_str, meta in answer_key.items():
        given = raw_answers.get(tartib_str)
        correct_letter = meta["correct_letter_shown_to_student"]
        ball = float(meta.get("ball", 1))
        fan = _subject_group_label(meta)  # YANGI: fan_group bo'yicha guruhlash

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

    return {
        "raw_answers": raw_answers,
        "correct": correct, "incorrect": incorrect, "blank": blank, "ambiguous": ambiguous,
        "total_score": total_score, "per_subject": per_subject,
        "detected_variant": detected_variant, "variant_mismatch": variant_mismatch,
    }


def compute_scores(db: Session, booklet_id: str, report: dict) -> dict:
    """exam_student topadi, ballarni hisoblaydi -- hali ham DB'ga yozmaydi."""
    exam_student = (
        db.query(models.ExamStudent)
        .filter(models.ExamStudent.booklet_id == booklet_id)
        .first()
    )
    if not exam_student:
        raise OmrError(f"Booklet ID topilmadi: {booklet_id}")

    raw_answers: dict[str, str | None] = {}
    for q in report["questions"]:
        key = str(q.question)
        raw_answers[key] = None if q.status == "blank" else ("MULTI" if q.status == "uncertain" else q.answer)

    detected_variant = report.get("detected_paper_variant")
    expected_variant = exam_student.paper_variant_number
    variant_mismatch = expected_variant is not None and (
        detected_variant is None or detected_variant != expected_variant
    )

    scores = _score_from_raw_answers(
        exam_student.answer_key_json, raw_answers, detected_variant, variant_mismatch
    )
    scores["exam_student_id"] = exam_student.id
    return scores


def recompute_scores_with_corrections(
    db: Session, exam_student_id: str, previous_scores: dict, corrections: dict[str, str | None]
) -> dict:
    """Qo'lda tuzatilgan javoblar bilan ballarni QAYTA hisoblaydi.
    DB'ga hech narsa yozmaydi -- hali ham 'pending' holatda."""
    exam_student = db.get(models.ExamStudent, exam_student_id)
    if not exam_student:
        raise OmrError("ExamStudent topilmadi (eskirgan holat)")

    raw_answers = dict(previous_scores["raw_answers"])
    raw_answers.update(corrections)

    scores = _score_from_raw_answers(
        exam_student.answer_key_json, raw_answers,
        previous_scores["detected_variant"], previous_scores["variant_mismatch"],
    )
    scores["exam_student_id"] = exam_student_id
    return scores


def save_result(db: Session, exam_student_id: str, scores: dict, warped_image) -> models.Result:
    """Rasmiy Result yozuvini yaratadi + natija PDF generatsiya qiladi.
    Faqat shu funksiya chaqirilganda DB'ga yoziladi."""
    exam_student = db.get(models.ExamStudent, exam_student_id)
    if not exam_student:
        raise OmrError("ExamStudent topilmadi (eskirgan holat)")

    if exam_student.result is not None:
        db.delete(exam_student.result)
        db.flush()

    status = (
        models.ResultStatus.needs_review
        if (scores["ambiguous"] > 0 or scores["variant_mismatch"])
        else models.ResultStatus.ok
    )

    result = models.Result(
        exam_student_id=exam_student.id,
        raw_answers_json=scores["raw_answers"],
        correct_count=scores["correct"], incorrect_count=scores["incorrect"],
        blank_count=scores["blank"], ambiguous_count=scores["ambiguous"],
        total_score=scores["total_score"], per_subject_json=scores["per_subject"],
        detected_paper_variant=scores["detected_variant"],
        variant_mismatch=scores["variant_mismatch"], status=status,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    try:
        student = exam_student.student
        group_name = student.group.name if student.group else ""
        exam = exam_student.exam
        answer_key = exam_student.answer_key_json

        scanned_path = _save_scanned_preview(warped_image, result.id)
        download_url = _build_download_url(result.id)

        exam_name = ""
        if exam_student.variant and exam_student.variant.test_set:
            exam_name = exam_student.variant.test_set.name
        elif exam and exam.toplam:  # YANGI: Toplam-asosidagi imtihonlarda variant yo'q
            exam_name = exam.toplam.name
        variant_label = exam_student.variant.label if exam_student.variant else None

        pdf_path = Path(settings.OUTPUT_DIR) / "results" / f"{result.id}.pdf"
        generate_result_pdf(
            output_path=str(pdf_path),
            student_full_name=student.full_name,
            group_name=group_name,
            exam_name=exam_name,
            exam_code=exam.exam_code if exam else "",
            total_score=scores["total_score"],
            total_questions=exam.total_questions if exam else len(answer_key),
            raw_answers=scores["raw_answers"],
            answer_key=answer_key,
            per_subject=scores["per_subject"],
            scanned_image_path=scanned_path,
            download_url=download_url,
            variant_label=variant_label,
            # YANGI: statistikani qayta hisoblamasdan to'g'ridan-to'g'ri uzatamiz
            correct_count=scores["correct"], incorrect_count=scores["incorrect"],
            blank_count=scores["blank"], ambiguous_count=scores["ambiguous"],
            checked_at=result.checked_at,
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
        fan = _subject_group_label(meta)  # YANGI: fan_group bo'yicha guruhlash

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

    # YANGI (Savollar banki): tuzatilgan javoblar bilan statistikani
    # ham qayta sinxronlaymiz (sync_attempts_for_exam_student
    # IDEMPOTENT -- avvalgi yozuvlarni o'chirib qayta yozadi, shuning
    # uchun bir necha marta tuzatilsa ham statistika noto'g'ri
    # ko'paymaydi).
    if exam_student.exam and exam_student.exam.toplam_id:
        try:
            from app.services.bank_service import sync_attempts_for_exam_student
            sync_attempts_for_exam_student(db, exam_student, raw_answers)
        except Exception:  # noqa: BLE001
            logger.exception("Savollar banki statistikasini yangilashda xato -- tuzatish baribir saqlandi")

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
        elif exam and exam.toplam:  # YANGI: Toplam-asosidagi imtihonlarda variant yo'q
            exam_name = exam.toplam.name

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
            # YANGI: statistikani qayta hisoblamasdan to'g'ridan-to'g'ri uzatamiz
            correct_count=result.correct_count, incorrect_count=result.incorrect_count,
            blank_count=result.blank_count, ambiguous_count=result.ambiguous_count,
            checked_at=result.checked_at,
        )
        result.result_pdf_path = str(pdf_path)
        db.commit()
        db.refresh(result)
    except Exception:  # noqa: BLE001
        logger.exception("Qo'lda tuzatishdan keyin natija PDF qayta generatsiyasida xato")

    return result
