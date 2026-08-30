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
import shutil
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


import logging; logger = logging.getLogger("omrmeroj.exam")

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

def _assign_paper_variants(students: list[models.Student], variant_count: int, rng: random.Random) -> dict[str, int]:
    """
    Har bir talabaga TEST VARIANTINI (1..variant_count) taqsimlaydi:
      - guruh IMKON QADAR TENG bo'laklarga bo'linadi (masalan 21 talaba,
        2 variant -> 11 va 10), qaysi talabaga qaysi variant tegishi esa
        random.
      - variant_count <= 1 bo'lsa, hammaga 1 qaytariladi (variant
        belgilash umuman kerak emas).
    """
    if variant_count <= 1:
        return {s.id: 1 for s in students}

    n = len(students)
    base, remainder = divmod(n, variant_count)
    pool: list[int] = []
    for variant_idx in range(1, variant_count + 1):
        count = base + (1 if variant_idx <= remainder else 0)
        pool.extend([variant_idx] * count)

    rng.shuffle(pool)
    return {student.id: pool[i] for i, student in enumerate(students)}

def _question_to_dict(q: models.Question) -> dict:
    return {
        "id": q.id, 
        "tartib": q.tartib, 
        "fan": q.fan, 
        "ball": q.ball,
        "savol_html": q.savol_html,  # BU MUHIM
        "savol_rasm_url": q.savol_rasm_url, 
        "jadval_html": q.jadval_html,
        "variant_a_html": q.variant_a_html,  # BU MUHIM
        "variant_b_html": q.variant_b_html,  # BU MUHIM
        "variant_c_html": q.variant_c_html,  # BU MUHIM
        "variant_d_html": q.variant_d_html,  # BU MUHIM
        "togri_javob": q.togri_javob,
    }


def _build_subject_blocks(questions: list[dict]) -> list[SubjectBlock]:
    ordered = sorted(questions, key=lambda q: q["tartib"])
    total = len(ordered)

    index_ranges = [(0, min(30, total))]
    if total > 30:
        index_ranges.append((30, min(60, total)))
    if total > 60:
        index_ranges.append((60, min(90, total)))

    blocks: list[SubjectBlock] = []
    for start_idx, end_idx in index_ranges:
        part = ordered[start_idx:end_idx]
        if not part:
            continue
        first, last = part[0], part[-1]
        fanlar = list(dict.fromkeys(q["fan"] for q in part))
        subject_name = ", ".join(fanlar)
        distinct_balls = {q["ball"] for q in part}
        blocks.append(SubjectBlock(
            start=first["tartib"], end=last["tartib"],
            subject=subject_name, point=first["ball"],
            mixed_points=len(distinct_balls) > 1,
        ))
    return blocks


def _build_true_subject_breakdown(questions: list[dict]) -> list[SubjectBlock]:
    """Savollarni ASL tartib bo'yicha saralab, ketma-ket bir xil
    (fan, ball) segmentlariga bo'ladi -- har bir segment alohida
    SubjectBlock (masalan: 1-10 'Ona tili' 1.1, 11-20 'Matematika' 1.1,
    21-30 'Tarix' 1.1, 31-60 'Matematika' 3.1, 61-90 'Fizika' 2.1).

    MUHIM: bu funksiya 'Matematika' nomini ikki marta -- turli ball
    bilan -- alohida-alohida blok sifatida qaytaradi. Bu ANIQ shu
    funksiya natijasi asosida _tartib_to_group_label() har bir savolga
    noyob guruh nomi biriktiradi (pastga qarang)."""
    ordered = sorted(questions, key=lambda q: q["tartib"])

    blocks: list[SubjectBlock] = []
    current_key = None
    start = prev_tartib = ball = fan_name = None

    for q in ordered:
        key = (q["fan"], q["ball"])
        if key != current_key:
            if current_key is not None:
                blocks.append(SubjectBlock(start=start, end=prev_tartib, subject=fan_name, point=ball))
            current_key = key
            start = q["tartib"]
            ball = q["ball"]
            fan_name = q["fan"]
        prev_tartib = q["tartib"]

    if current_key is not None:
        blocks.append(SubjectBlock(start=start, end=prev_tartib, subject=fan_name, point=ball))

    return blocks


def _tartib_to_group_label(questions: list[dict]) -> dict[int, str]:
    """
    Har bir savol tartibini, uning tegishli (fan, ball) guruhida
    ko'rsatiladigan NOM bilan bog'laydi.

    MUHIM: agar bir xil fan nomi (masalan "Matematika") ikki xil ball
    bilan alohida guruh sifatida uchrasa -- masalan majburiy fanlar
    ichida 1.1 ball bilan, va alohida asosiy fan sifatida 3.1 ball
    bilan -- ular endi natija/statistikada bitta "Matematika"ga
    birlashib QOLMAYDI. Ikkinchi (va undan keyingi) uchrashuv ballni
    ham nomga qo'shib ajratiladi: "Matematika (3.1 ball)".

    Bitta marta uchraydigan fanlar (masalan "Fizika") nomi
    o'zgarishsiz qoladi -- keraksiz "(2.1 ball)" qo'shilmaydi.
    """
    blocks = _build_true_subject_breakdown(questions)

    label_counts: dict[str, int] = {}
    for block in blocks:
        label_counts[block.subject] = label_counts.get(block.subject, 0) + 1

    mapping: dict[int, str] = {}
    for block in blocks:
        label = block.subject
        if label_counts[block.subject] > 1:
            label = f"{block.subject} ({block.point:g} ball)"
        for tartib in range(block.start, block.end + 1):
            mapping[tartib] = label
    return mapping


def create_exam_job(
    db: Session, teacher: models.User, group_id: str, test_set_id: str,
    paper_variant_count: int = 1, name: str | None = None,  # YANGI
) -> tuple[models.Exam, models.ProcessingJob]:
    """Faqat Exam + ProcessingJob yozuvlarini yaratadi (tez, sinxron).
    Haqiqiy PDF generatsiyasi _run_exam_generation() orqali orqada ishlaydi."""
    group = db.get(models.Group, group_id)
    if not group or group.teacher_id != teacher.id:
        raise ExamServiceError("Guruh topilmadi")

    test_set = db.get(models.TestSet, test_set_id)
    if not test_set or test_set.teacher_id != teacher.id:
        raise ExamServiceError("Test topilmadi")

    test_variants = (
        db.query(models.Variant)
        .filter(models.Variant.test_set_id == test_set.id)
        .order_by(models.Variant.order_index)
        .all()
    )
    if not test_variants:
        raise ExamServiceError("Test to'plamida hech qanday variant yo'q")

    students = [s for s in group.students if s.is_active]
    if not students:
        raise ExamServiceError("Guruhda faol o'quvchi yo'q")

    exam = models.Exam(
        name=name,  # YANGI
        teacher_id=teacher.id, group_id=group.id, test_set_id=test_set.id,
        exam_code=_generate_exam_code(), total_questions=test_set.total_questions,
        status=models.ExamStatus.generating,
    )
    db.add(exam)
    db.flush()

    job = models.ProcessingJob(kind="booklet_generation", exam_id=exam.id, status=models.JobStatus.queued)
    db.add(job)
    db.commit()
    db.refresh(exam)
    db.refresh(job)
    return exam, job


def run_exam_generation(exam_id: str, job_id: str, paper_variant_count: int) -> None:
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        exam = db.get(models.Exam, exam_id)
        job = db.get(models.ProcessingJob, job_id)
        if not exam or not job:
            logger.error("Exam yoki job topilmadi")
            return

        job.status = models.JobStatus.processing
        db.commit()

        # ✅ Tuzatish: group va test_set ni alohida olish
        group = db.get(models.Group, exam.group_id)
        if not group:
            raise ExamServiceError("Guruh topilmadi")
        test_set = db.get(models.TestSet, exam.test_set_id)
        if not test_set:
            raise ExamServiceError("Test to'plami topilmadi")

        test_variants = (
            db.query(models.Variant)
            .filter(models.Variant.test_set_id == test_set.id)
            .order_by(models.Variant.order_index)
            .all()
        )
        students = [s for s in group.students if s.is_active]

        if not test_variants:
            raise ExamServiceError("Test to'plamida variantlar mavjud emas")
        if not students:
            raise ExamServiceError("Guruhda faol o'quvchilar mavjud emas")

        # --- pastdagi blok eski create_exam() dagi try/except bilan AYNAN BIR XIL
        #     (variant taqsimlash, booklet+javob varag'i generatsiyasi, ZIP) ---
        effective_variant_count = min(paper_variant_count, len(test_variants))
        variant_rng = random.Random(f"{exam.id}-paper-variant")
        paper_variant_map = _assign_paper_variants(students, effective_variant_count, variant_rng)

        output_root = Path(settings.OUTPUT_DIR) / exam.id
        savollar_dir = output_root / "Savollar"
        javoblar_dir = output_root / "Javoblar_varaqasi"
        savollar_dir.mkdir(parents=True, exist_ok=True)
        javoblar_dir.mkdir(parents=True, exist_ok=True)

        total = len(students)
        for idx, student in enumerate(students, start=1):
            rng = random.Random(f"{exam.id}-{student.id}")
            booklet_id = _generate_booklet_id(db, rng)
            paper_variant_number = paper_variant_map[student.id] if paper_variant_count > 1 else 1
            variant_index = (paper_variant_number - 1) % len(test_variants)
            selected_variant = test_variants[variant_index]

            questions = [_question_to_dict(q) for q in selected_variant.questions]
            if not questions:
                raise ExamServiceError(f"'{selected_variant.label}' variantida savollar yo'q")

            subject_blocks = _build_subject_blocks(questions)
            subject_breakdown = _build_true_subject_breakdown(questions)

            # Bir xil fan nomi turli ball bilan alohida guruh bo'lsa
            # (masalan majburiy fanlar ichidagi Matematika 1.1 ball vs
            # asosiy fan sifatidagi Matematika 3.1 ball), natija
            # statistikasida bittaga birlashib QOLMASLIGI uchun har bir
            # savolga aniq guruh nomi biriktiriladi.
            group_labels = _tartib_to_group_label(questions)
            for q in questions:
                q["fan_group"] = group_labels[q["tartib"]]

            sheet_exam = SheetExam(
                exam_id=exam.exam_code, exam_name=test_set.name,
                total_questions=exam.total_questions, subjects=subject_blocks,
                subject_breakdown=subject_breakdown,
            )
            rendered_questions, answer_key = build_shuffled_booklet(questions, seed=f"{exam.id}-{booklet_id}")

            sheet_student = SheetStudent(
                id=student.id, first_name=student.first_name, last_name=student.last_name,
                father_name=student.middle_name or "", group_name=group.name,
            )
            sheet_booklet = SheetBooklet(
                booklet_id=booklet_id, exam_id=exam.exam_code, student_id=student.id,
                variant_number=paper_variant_number if paper_variant_count > 1 else None,
            )

            safe_name = f"{student.last_name}_{student.first_name}".replace(" ", "_")
            booklet_path = savollar_dir / f"{safe_name}_{booklet_id}_Savol.pdf"
            sheet_path = javoblar_dir / f"{safe_name}_{booklet_id}_Javoblar.pdf"

            render_booklet_pdf(
                student={"full_name": sheet_student.full_name, "group_name": group.name},
                exam_id=exam.exam_code, booklet_id=booklet_id,
                rendered_questions=rendered_questions, output_path=str(booklet_path),
                variant_label=selected_variant.label,
                exam_name=test_set.name,  # YANGI -- "Imtihon haqida" kartasida ko'rsatiladi
            )
            generate_answer_sheet(
                output_path=str(sheet_path), student=sheet_student, exam=sheet_exam, booklet=sheet_booklet,
            )

            db.add(models.ExamStudent(
                exam_id=exam.id, student_id=student.id, variant_id=selected_variant.id,
                booklet_id=booklet_id, answer_key_json=answer_key,
                booklet_pdf_path=str(booklet_path), answer_sheet_pdf_path=str(sheet_path),
                paper_variant_number=paper_variant_number if paper_variant_count > 1 else None,
            ))

            job.progress = int(idx / total * 100)
            db.commit()

        zip_name = f"{group.name}_{test_set.name}.zip".replace(" ", "_")
        zip_path = output_root / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in savollar_dir.glob("*.pdf"):
                zf.write(f, arcname=f"Savollar/{f.name}")
            for f in javoblar_dir.glob("*.pdf"):
                zf.write(f, arcname=f"Javoblar_varaqasi/{f.name}")

        exam.status = models.ExamStatus.ready
        exam.zip_path = str(zip_path)   # <-- bu qator muhim
        job.status = models.JobStatus.completed
        job.progress = 100
        db.commit()

    except Exception as e:
        db.rollback()
        exam = db.get(models.Exam, exam_id)
        job = db.get(models.ProcessingJob, job_id)
        if exam:
            exam.status = models.ExamStatus.failed
        if job:
            job.status = models.JobStatus.failed
            job.error_message = str(e)
        db.commit()
        logger.exception("Exam generatsiyasida xato: exam_id=%s", exam_id)
    finally:
        db.close()

def delete_exam(db: Session, exam: models.Exam) -> None:
    """Exam + unga tegishli barcha fayllarni (booklet/javob varag'i PDF,
    natija PDF, skan rasm, zip) diskdan va DB'dan o'chiradi."""
    for exam_student in exam.students:
        result = exam_student.result
        if result is not None:
            if result.result_pdf_path:
                Path(result.result_pdf_path).unlink(missing_ok=True)
            scan_path = Path(settings.OUTPUT_DIR) / "result_scans" / f"{result.id}.jpg"
            scan_path.unlink(missing_ok=True)
            db.delete(result)
        if exam_student.booklet_pdf_path:
            Path(exam_student.booklet_pdf_path).unlink(missing_ok=True)
        if exam_student.answer_sheet_pdf_path:
            Path(exam_student.answer_sheet_pdf_path).unlink(missing_ok=True)

    db.flush()

    if exam.zip_path:
        Path(exam.zip_path).unlink(missing_ok=True)
    shutil.rmtree(Path(settings.OUTPUT_DIR) / exam.id, ignore_errors=True)

    db.delete(exam)
    db.commit()


# =============================================================
# YANGI (Savollar banki, 3-qism): Toplam-asosidagi imtihon yaratish
#
# create_exam_job()/run_exam_generation()ning parallel varianti --
# ular O'ZGARTIRILMAGAN, qoladi. Bu funksiyalar Variant/TestSet
# o'rniga Toplam ishlatadi, lekin xuddi shu pipeline bosqichlaridan
# (randomizatsiya, PDF generatsiya, ZIP) foydalanadi.
#
# MUHIM CHEKLOV: Toplam'da hozircha bir nechta "qog'oz varianti"
# (paper variant, ya'ni bir nechta mustaqil Variant orasida talabalarni
# taqsimlash) tushunchasi YO'Q -- har bir talaba bir xil savollar
# to'plamidan (faqat A/B/C/D va pozitsiya aralashtirilgan holda)
# booklet oladi. Ko'p-variantli Toplam-asosidagi imtihon kerak bo'lsa,
# bu -- kelajakdagi alohida ish.
# =============================================================

def create_toplam_exam_job(
    db: Session, teacher: models.User, group_id: str, toplam_id: str,
    name: str | None = None,
) -> tuple[models.Exam, models.ProcessingJob]:
    from app.services.bank_service import get_toplam, BankServiceError

    group = db.get(models.Group, group_id)
    if not group or group.teacher_id != teacher.id:
        raise ExamServiceError("Guruh topilmadi")

    try:
        toplam = get_toplam(db, toplam_id, teacher_id=teacher.id)
    except BankServiceError as e:
        raise ExamServiceError(str(e))

    question_count = (
        db.query(models.ToplamQuestion)
        .filter(models.ToplamQuestion.toplam_id == toplam.id)
        .count()
    )
    if question_count == 0:
        raise ExamServiceError("To'plamda hech qanday savol yo'q")

    students = [s for s in group.students if s.is_active]
    if not students:
        raise ExamServiceError("Guruhda faol o'quvchi yo'q")

    exam = models.Exam(
        name=name or toplam.name,
        teacher_id=teacher.id, group_id=group.id, toplam_id=toplam.id,
        exam_code=_generate_exam_code(), total_questions=question_count,
        status=models.ExamStatus.generating,
    )
    db.add(exam)
    db.flush()

    job = models.ProcessingJob(kind="booklet_generation", exam_id=exam.id, status=models.JobStatus.queued)
    db.add(job)
    db.commit()
    db.refresh(exam)
    db.refresh(job)
    return exam, job


def run_toplam_exam_generation(exam_id: str, job_id: str) -> None:
    from app.database import SessionLocal
    from app.services.bank_service import toplam_to_question_dicts

    db = SessionLocal()
    try:
        exam = db.get(models.Exam, exam_id)
        job = db.get(models.ProcessingJob, job_id)
        if not exam or not job:
            logger.error("Exam yoki job topilmadi")
            return

        job.status = models.JobStatus.processing
        db.commit()

        group = db.get(models.Group, exam.group_id)
        if not group:
            raise ExamServiceError("Guruh topilmadi")
        toplam = db.get(models.Toplam, exam.toplam_id)
        if not toplam:
            raise ExamServiceError("To'plam topilmadi")

        students = [s for s in group.students if s.is_active]
        if not students:
            raise ExamServiceError("Guruhda faol o'quvchilar mavjud emas")

        # Bir marta bazadan olamiz -- pastda har bir talaba uchun
        # mustaqil (shallow copy) nusxa yasaymiz, chunki har safar
        # fan_group maydoni yozib qo'yiladi (eski koddagi
        # _question_to_dict() har safar YANGI dict qaytargani bilan
        # bir xil xavfsizlikni saqlash uchun -- umumiy ro'yxatni
        # to'g'ridan-to'g'ri mutatsiya qilib, talabalar orasida
        # tasodifiy "sizib chiqish"ning oldini olamiz).
        questions_base = toplam_to_question_dicts(db, toplam.id, teacher_id=exam.teacher_id)

        output_root = Path(settings.OUTPUT_DIR) / exam.id
        savollar_dir = output_root / "Savollar"
        javoblar_dir = output_root / "Javoblar_varaqasi"
        savollar_dir.mkdir(parents=True, exist_ok=True)
        javoblar_dir.mkdir(parents=True, exist_ok=True)

        total = len(students)
        for idx, student in enumerate(students, start=1):
            rng = random.Random(f"{exam.id}-{student.id}")
            booklet_id = _generate_booklet_id(db, rng)

            questions = [dict(q) for q in questions_base]

            subject_blocks = _build_subject_blocks(questions)
            subject_breakdown = _build_true_subject_breakdown(questions)
            group_labels = _tartib_to_group_label(questions)
            for q in questions:
                q["fan_group"] = group_labels[q["tartib"]]

            sheet_exam = SheetExam(
                exam_id=exam.exam_code, exam_name=toplam.name,
                total_questions=exam.total_questions, subjects=subject_blocks,
                subject_breakdown=subject_breakdown,
            )
            rendered_questions, answer_key = build_shuffled_booklet(questions, seed=f"{exam.id}-{booklet_id}")

            sheet_student = SheetStudent(
                id=student.id, first_name=student.first_name, last_name=student.last_name,
                father_name=student.middle_name or "", group_name=group.name,
            )
            sheet_booklet = SheetBooklet(
                booklet_id=booklet_id, exam_id=exam.exam_code, student_id=student.id,
                variant_number=None,
            )

            safe_name = f"{student.last_name}_{student.first_name}".replace(" ", "_")
            booklet_path = savollar_dir / f"{safe_name}_{booklet_id}_Savol.pdf"
            sheet_path = javoblar_dir / f"{safe_name}_{booklet_id}_Javoblar.pdf"

            render_booklet_pdf(
                student={"full_name": sheet_student.full_name, "group_name": group.name},
                exam_id=exam.exam_code, booklet_id=booklet_id,
                rendered_questions=rendered_questions, output_path=str(booklet_path),
                variant_label=None,
                exam_name=toplam.name,
            )
            generate_answer_sheet(
                output_path=str(sheet_path), student=sheet_student, exam=sheet_exam, booklet=sheet_booklet,
            )

            db.add(models.ExamStudent(
                exam_id=exam.id, student_id=student.id, variant_id=None,
                booklet_id=booklet_id, answer_key_json=answer_key,
                booklet_pdf_path=str(booklet_path), answer_sheet_pdf_path=str(sheet_path),
                paper_variant_number=None,
            ))

            job.progress = int(idx / total * 100)
            db.commit()

        zip_name = f"{group.name}_{toplam.name}.zip".replace(" ", "_")
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

    except Exception as e:
        db.rollback()
        exam = db.get(models.Exam, exam_id)
        job = db.get(models.ProcessingJob, job_id)
        if exam:
            exam.status = models.ExamStatus.failed
        if job:
            job.status = models.JobStatus.failed
            job.error_message = str(e)
        db.commit()
        logger.exception("Toplam-exam generatsiyasida xato: exam_id=%s", exam_id)
    finally:
        db.close()
