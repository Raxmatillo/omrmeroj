# -*- coding: utf-8 -*-
"""
Imtihon yaratish: guruh + test to'plamini biriktirib, har bir talaba
uchun individual savollar kitobi + javoblar varag'i generatsiya qiladi,
ExamStudent.answer_key_json'ni to'ldiradi va hammasini ZIP'ga yig'adi.

Hozircha SINXRON bajariladi (request ichida). TZ Celery/ARQ background
worker talab qiladi -- loyihaning joriy bosqichida (Docker/Redis hali
yo'q) bu keyingi qadamga qoldirilgan. ProcessingJob yozuvi saqlanadi,
shuning uchun keyinchalik bu funksiyani deyarli o'zgarishsiz background
workerga ko'chirish mumkin bo'ladi.
"""
from __future__ import annotations

import random
import secrets
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.omr.answer_sheet_generator import (
    Student as SheetStudent,
    Exam as SheetExam,
    SubjectBlock,
    Booklet as SheetBooklet,
    generate_answer_sheet,
)
from app.omr.booklet_html_generator import render_booklet_pdf
from app.omr.randomization import build_shuffled_booklet


class ExamServiceError(Exception):
    """Foydalanuvchiga to'g'ridan-to'g'ri ko'rsatsa bo'ladigan xato."""


def _generate_exam_code() -> str:
    return "EX-" + secrets.token_hex(3).upper()


def _generate_booklet_id(db: Session, rng: random.Random) -> str:
    for _ in range(50):
        candidate = "".join(str(rng.randint(0, 9)) for _ in range(7))
        exists = db.query(models.ExamStudent).filter(models.ExamStudent.booklet_id == candidate).first()
        if not exists:
            return candidate
    raise ExamServiceError("Noyob booklet ID generatsiya qilib bo'lmadi, qayta urinib ko'ring")


def _question_to_dict(q: models.Question) -> dict:
    return {
        "id": q.id, "tartib": q.tartib, "fan": q.fan, "ball": q.ball,
        "savol_html": q.savol_html, "savol_rasm_url": q.savol_rasm_url, "jadval_html": q.jadval_html,
        "variant_a_html": q.variant_a_html, "variant_b_html": q.variant_b_html,
        "variant_c_html": q.variant_c_html, "variant_d_html": q.variant_d_html,
        "togri_javob": q.togri_javob,
    }


def _build_subject_blocks(questions: list[dict]) -> list[SubjectBlock]:
    """Javoblar varag'idagi (1-30 / 31-60 / 61-90) fan bloklari -- asl
    `tartib` pozitsiyalaridan hosil qilinadi. Randomizatsiyadan keyin ham
    bu SLOTLAR o'zgarmaydi, faqat qaysi savol qaysi pozitsiyada
    turishi o'zgaradi."""
    blocks: list[SubjectBlock] = []
    ordered = sorted(questions, key=lambda q: q["tartib"])
    current_fan = None
    start = None
    prev_tartib = None
    ball = None
    for q in ordered:
        if q["fan"] != current_fan:
            if current_fan is not None:
                blocks.append(SubjectBlock(start=start, end=prev_tartib, subject=current_fan, point=ball))
            current_fan = q["fan"]
            start = q["tartib"]
            ball = q["ball"]
        prev_tartib = q["tartib"]
    if current_fan is not None:
        blocks.append(SubjectBlock(start=start, end=prev_tartib, subject=current_fan, point=ball))
    return blocks


def create_exam(db: Session, teacher: models.User, group_id: str, test_set_id: str) -> models.Exam:
    group = db.get(models.Group, group_id)
    if not group or group.teacher_id != teacher.id:
        raise ExamServiceError("Guruh topilmadi")

    test_set = db.get(models.TestSet, test_set_id)
    if not test_set or test_set.teacher_id != teacher.id:
        raise ExamServiceError("Test topilmadi")

    source_variant = (
        db.query(models.Variant)
        .filter(models.Variant.test_set_id == test_set.id)
        .order_by(models.Variant.order_index)
        .first()
    )
    if not source_variant:
        raise ExamServiceError("Test to'plamida hech qanday variant yo'q")

    students = [s for s in group.students if s.is_active]
    if not students:
        raise ExamServiceError("Guruhda faol o'quvchi yo'q")

    questions = [_question_to_dict(q) for q in source_variant.questions]
    if not questions:
        raise ExamServiceError("Variantda savollar yo'q")

    exam = models.Exam(
        teacher_id=teacher.id, group_id=group.id, test_set_id=test_set.id,
        exam_code=_generate_exam_code(), total_questions=test_set.total_questions,
        status=models.ExamStatus.generating,
    )
    db.add(exam)
    db.flush()

    job = models.ProcessingJob(kind="booklet_generation", exam_id=exam.id, status=models.JobStatus.processing)
    db.add(job)
    # Bu bosqichni alohida commit qilamiz -- shu bilan pastda xato bo'lsa
    # rollback FAQAT generatsiya qismini bekor qiladi, exam/job yozuvi esa
    # "failed" holatida saqlanib qoladi (userga ko'rsatish uchun).
    db.commit()
    db.refresh(exam)
    db.refresh(job)

    output_root = Path(settings.OUTPUT_DIR) / exam.id
    savollar_dir = output_root / "Savollar"
    javoblar_dir = output_root / "Javoblar_varaqasi"
    savollar_dir.mkdir(parents=True, exist_ok=True)
    javoblar_dir.mkdir(parents=True, exist_ok=True)

    subject_blocks = _build_subject_blocks(questions)
    sheet_exam = SheetExam(
        exam_id=exam.exam_code, exam_name=test_set.name,
        total_questions=exam.total_questions, subjects=subject_blocks,
    )

    try:
        for student in students:
            rng = random.Random(f"{exam.id}-{student.id}")
            booklet_id = _generate_booklet_id(db, rng)

            rendered_questions, answer_key = build_shuffled_booklet(questions, seed=f"{exam.id}-{booklet_id}")

            sheet_student = SheetStudent(
                id=student.id, first_name=student.first_name, last_name=student.last_name,
                father_name=student.middle_name or "", group_name=group.name,
            )
            sheet_booklet = SheetBooklet(booklet_id=booklet_id, exam_id=exam.exam_code, student_id=student.id)

            safe_name = f"{student.last_name}_{student.first_name}".replace(" ", "_")
            booklet_path = savollar_dir / f"{safe_name}_{booklet_id}_Savol.pdf"
            sheet_path = javoblar_dir / f"{safe_name}_{booklet_id}_Javoblar.pdf"

            render_booklet_pdf(
                student={"full_name": sheet_student.full_name, "group_name": group.name},
                exam_id=exam.exam_code, booklet_id=booklet_id,
                rendered_questions=rendered_questions, output_path=str(booklet_path),
            )
            generate_answer_sheet(
                output_path=str(sheet_path), student=sheet_student, exam=sheet_exam, booklet=sheet_booklet,
            )

            db.add(models.ExamStudent(
                exam_id=exam.id, student_id=student.id, variant_id=source_variant.id,
                booklet_id=booklet_id, answer_key_json=answer_key,
                booklet_pdf_path=str(booklet_path), answer_sheet_pdf_path=str(sheet_path),
            ))

        db.flush()

        zip_name = f"{group.name}_{test_set.name}.zip".replace(" ", "_")
        zip_path = output_root / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in savollar_dir.glob("*.pdf"):
                zf.write(f, arcname=f"Savollar/{f.name}")
            for f in javoblar_dir.glob("*.pdf"):
                zf.write(f, arcname=f"Javoblar_varaqasi/{f.name}")

        exam.status = models.ExamStatus.ready
        exam.zip_path = str(zip_path)
        job.status = models.JobStatus.completed
        job.progress = 100
        db.commit()

    except Exception as e:  # noqa: BLE001
        db.rollback()
        exam.status = models.ExamStatus.failed
        job.status = models.JobStatus.failed
        job.error_message = str(e)
        db.commit()
        raise ExamServiceError(f"Imtihon generatsiyasida xato: {e}") from e

    db.refresh(exam)
    return exam