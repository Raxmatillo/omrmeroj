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
        "id": q.id, "tartib": q.tartib, "fan": q.fan, "ball": q.ball,
        "savol_html": q.savol_html, "savol_rasm_url": q.savol_rasm_url, "jadval_html": q.jadval_html,
        "variant_a_html": q.variant_a_html, "variant_b_html": q.variant_b_html,
        "variant_c_html": q.variant_c_html, "variant_d_html": q.variant_d_html,
        "togri_javob": q.togri_javob,
    }


def _build_subject_blocks(questions: list[dict]) -> list[SubjectBlock]:
    """
    Javoblar varag'idagi bloklarni USTUN chegaralari (1-30 / 31-60 / 61-90)
    bo'yicha yaratadi -- fan yoki ball o'zgarishiga qarab EMAS.

    MUHIM (2 marta tuzatilgan xato tarixi):
      v1 xato: har `fan` o'zgarganda yangi SubjectBlock ochardi ->
        distribute_subjects() (app/omr/answer_sheet_generator.py) bitta
        ustunga bir nechta blokni ketma-ket yozib, faqat OXIRGISINI
        qoldirardi. Natijada javoblar varag'ida faqat oxirgi fan
        guruhidagi savollar chiqardi.
      v2 xato (nozikroq zaiflik): tuzatilgan versiya savollarni
        HAQIQIY `tartib` QIYMATI bo'yicha filtrlardi
        (`start <= q["tartib"] <= end`). Bu odatiy holatda ishlaydi
        (app/utils/excel_import.py orqali import qilinganda `tartib`
        har doim ketma-ket 1..N beriladi), LEKIN agar `tartib`
        qiymatlarida takrorlanish yoki bo'shliq paydo bo'lsa (masalan
        qo'lda qo'shilgan savol, bir necha marta import, yoki boshqa
        bir kod yo'li Excel'dagi "T/r" ustunini to'g'ridan-to'g'ri
        `tartib` sifatida ishlatsa), filtr yana NOTO'G'RI (qisman)
        blok hosil qilib, xuddi shu "oxirgi N ta savol" muammosini
        qaytarishi mumkin edi.

    Shu sababli endi HAQIQIY tartib qiymatiga emas, TARTIBLANGAN
    RO'YXATDAGI POZITSIYAGA (indeksga) asoslanadi -- bu `tartib`
    maydonidagi har qanday takrorlanish/bo'shliqdan MUSTAQIL ravishda,
    har doim birinchi 30 tasi 1-ustunga, keyingi 30 tasi 2-ustunga,
    oxirgi 30 tasi 3-ustunga tushishini kafolatlaydi.

    Qoida (TZ bo'yicha):
      - savollar soni <= 30  -> HAMMASI 1-ustunda (1 ta blok)
      - savollar soni <= 60  -> 1-30 => 1-ustun, 31-60 => 2-ustun
      - savollar soni <= 90  -> 1-30 / 31-60 / 61-90 => mos ustunlar

    Bitta blok ichida bir nechta fan/ball bo'lishi mumkin (masalan 30
    savollik testda 3 xil fan aralash bo'lishi mumkin) -- bu holda fan
    nomlari vergul bilan birlashtirib ko'rsatiladi. `point` maydoni
    shu blokdagi BIRINCHI savolning ballini ko'rsatadi -- bu faqat
    ustun sarlavhasidagi ko'rsatkich, HAQIQIY baholash (omr_service.py)
    har bir savolning o'z `ball` qiymatidan foydalanadi, shuning uchun
    aralash ball bo'lsa ham natija noto'g'ri hisoblanmaydi.
    """
    ordered = sorted(questions, key=lambda q: q["tartib"])
    total = len(ordered)

    # Pozitsiya (indeks) bo'yicha kesimlar -- qiymat emas!
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
        # Takrorlarsiz, lekin uchrash tartibini saqlab fan nomlarini yig'amiz
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
    """
    Javoblar varag'idagi "O'QUVCHI MA'LUMOTLARI" qutisi ichidagi
    "Fan / Oraliq / Soni / Ball / Jami" jadvali uchun -- HAR BIR
    fan/ball guruhini ALOHIDA qator sifatida qaytaradi.

    MUHIM: `_build_subject_blocks()`dan farqi shu -- u ustunlarga
    bubble chizish uchun bloklarni USTUN chegarasiga (1-30/31-60/61-90)
    qarab birlashtiradi (bitta ustunda 3 xil fan bo'lsa ham bitta blok
    bo'ladi). Bu funksiya esa hech narsani birlashtirmaydi -- shuning
    uchun 30 talik testda 3 xil fan (masalan Majburiy fanlar 1.1 ball,
    Matematika 2.1 ball, Ingliz tili 3.1 ball, har birida 10tadan)
    bo'lsa, natijada 3 ta ALOHIDA qator qaytadi -- har biri o'z soni,
    balli va jami bali bilan. Bu ro'yxat FAQAT header jadvalini
    chizish uchun ishlatiladi, ustunlarga bubble chizishga ta'sir
    qilmaydi (buning uchun `_build_subject_blocks()` alohida
    ishlatiladi).
    """
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


def create_exam(
    db: Session, teacher: models.User, group_id: str, test_set_id: str,
    paper_variant_count: int = 1,
) -> models.Exam:
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

    # MUHIM: taqsimlash `exam.id` endi mavjud bo'lgach (seed sifatida
    # ishlatiladi), butun guruh bo'yicha BITTA marta qilinadi -- shu bilan
    # "yarmiga bitta, yarmiga boshqasi" balansi kafolatlanadi va exam
    # qayta generatsiya qilinsa ham bir xil taqsimot takrorlanadi.
    variant_rng = random.Random(f"{exam.id}-paper-variant")
    paper_variant_map = _assign_paper_variants(students, paper_variant_count, variant_rng)

    output_root = Path(settings.OUTPUT_DIR) / exam.id
    savollar_dir = output_root / "Savollar"
    javoblar_dir = output_root / "Javoblar_varaqasi"
    savollar_dir.mkdir(parents=True, exist_ok=True)
    javoblar_dir.mkdir(parents=True, exist_ok=True)

    subject_blocks = _build_subject_blocks(questions)              # ustunlar uchun (birlashtirilgan)
    subject_breakdown = _build_true_subject_breakdown(questions)    # header jadvali uchun (alohida qatorlar)
    sheet_exam = SheetExam(
        exam_id=exam.exam_code, exam_name=test_set.name,
        total_questions=exam.total_questions, subjects=subject_blocks,
        subject_breakdown=subject_breakdown,
    )

    try:
        for student in students:
            rng = random.Random(f"{exam.id}-{student.id}")
            booklet_id = _generate_booklet_id(db, rng)
            paper_variant_number = paper_variant_map[student.id] if paper_variant_count > 1 else None

            rendered_questions, answer_key = build_shuffled_booklet(questions, seed=f"{exam.id}-{booklet_id}")

            sheet_student = SheetStudent(
                id=student.id, first_name=student.first_name, last_name=student.last_name,
                father_name=student.middle_name or "", group_name=group.name,
            )
            sheet_booklet = SheetBooklet(
                booklet_id=booklet_id, exam_id=exam.exam_code, student_id=student.id,
                variant_number=paper_variant_number,
            )

            safe_name = f"{student.last_name}_{student.first_name}".replace(" ", "_")
            booklet_path = savollar_dir / f"{safe_name}_{booklet_id}_Savol.pdf"
            sheet_path = javoblar_dir / f"{safe_name}_{booklet_id}_Javoblar.pdf"

            render_booklet_pdf(
                student={"full_name": sheet_student.full_name, "group_name": group.name},
                exam_id=exam.exam_code, booklet_id=booklet_id,
                rendered_questions=rendered_questions, output_path=str(booklet_path),
                variant_number=paper_variant_number,
            )
            generate_answer_sheet(
                output_path=str(sheet_path), student=sheet_student, exam=sheet_exam, booklet=sheet_booklet,
            )

            db.add(models.ExamStudent(
                exam_id=exam.id, student_id=student.id, variant_id=source_variant.id,
                booklet_id=booklet_id, answer_key_json=answer_key,
                booklet_pdf_path=str(booklet_path), answer_sheet_pdf_path=str(sheet_path),
                paper_variant_number=paper_variant_number,
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