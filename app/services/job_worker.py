# -*- coding: utf-8 -*-
"""
YANGI: ProcessingJob'larni CHINDAN HAM ORQADA, DAVOMLI (durable) tarzda
bajaradigan ishchi (worker) tsikli.

MUAMMO (avvalgi holat): `ProcessingJob` jadvali bor edi, lekin u faqat
holat KO'RSATKICHI edi -- haqiqiy ish FastAPI'ning BackgroundTasks
(exams.py) yoki xotiradagi `pending_results` dict (results.py) orqali,
so'rov bilan BIR XIL server jarayoni ichida bajarilardi. Agar server
o'sha payt qulasa yoki qayta ishga tushirilsa -- ish hech qanday iz
qoldirmasdan yo'qolardi (job "processing" holatida abadiy qolib
ketardi, hech kim uni qayta boshlamasdi).

YECHIM: bu modul FastAPI lifespan orqali ALOHIDA, DOIMIY ishlaydigan
asyncio tsikl sifatida ishga tushadi. U:
  1. Har POLL_INTERVAL_SECONDS soniyada DB'dan "queued" holatidagi
     ishlarni qidiradi.
  2. Topilsa -- "processing" deb belgilaydi, keyin turiga (kind)
     qarab tegishli funksiyani ALOHIDA THREAD'da (asyncio.to_thread)
     chaqiradi (chunki OMR/PDF ishlari CPU-band, asosiy event loop'ni
     bloklamasligi kerak).
  3. MUHIM -- ISHGA TUSHGANDA (startup): agar avvalgi ishga tushganda
     "processing" holatida QOLIB KETGAN ishlar bo'lsa (server o'sha
     payt qulagani sababli), ularni avtomatik "queued" holatiga
     QAYTARADI -- shu bilan keyingi tsiklda avtomatik qayta ishga
     tushadi. Agar bitta ish MAX_ATTEMPTS martadan ko'p qayta
     urinilgan bo'lsa, "failed" deb belgilanadi (cheksiz qayta urinish
     sikliga tushib qolmaslik uchun).

Bu -- Celery/Redis O'RNIGA emas, balki ular hali ORTIQCHA bo'lgan
bosqichda (bitta kompyuter, past-o'rta yuklama) YETARLI, oddiy va
qo'shimcha infratuzilma talab qilmaydigan yechim. SQLite'ning o'zi --
"navbat jadvali" vazifasini bajaradi.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from app import models
from app.database import SessionLocal

logger = logging.getLogger("omrmeroj.job_worker")

POLL_INTERVAL_SECONDS = 3
MAX_ATTEMPTS = 3

_worker_task: "asyncio.Task | None" = None


def _recover_interrupted_jobs() -> None:
    """Server oldingi safar QULAB TUSHGANDA "processing" holatida qolib
    ketgan ishlarni topadi. MAX_ATTEMPTS ichida bo'lsa -- "queued"ga
    qaytarib, avtomatik qayta ishga tushishini ta'minlaydi. Attempts
    tugagan bo'lsa -- "failed" deb belgilab, foydalanuvchiga aniq xabar
    qoldiradi (abadiy "processing" holatida osilib qolmasligi uchun)."""
    db = SessionLocal()
    try:
        stuck = db.query(models.ProcessingJob).filter(
            models.ProcessingJob.status == models.JobStatus.processing
        ).all()
        for job in stuck:
            job.attempts = (job.attempts or 0) + 1
            if job.attempts > MAX_ATTEMPTS:
                job.status = models.JobStatus.failed
                job.error_message = (
                    "Server qayta ishga tushirilganda bu ish yakunlanmagan edi "
                    f"va {MAX_ATTEMPTS} marta qayta urinishdan keyin ham "
                    "muvaffaqiyatsiz bo'ldi."
                )
                job.finished_at = datetime.utcnow()
                logger.warning("Ish %s (%s) urinishlar tugagani uchun failed deb belgilandi", job.id, job.kind)
            else:
                job.status = models.JobStatus.queued
                logger.warning(
                    "Ish %s (%s) 'processing' holatida qolib ketgan edi (server qulagan "
                    "bo'lishi mumkin) -- qaytadan navbatga qo'yildi (%d/%d urinish)",
                    job.id, job.kind, job.attempts, MAX_ATTEMPTS,
                )
        db.commit()
    finally:
        db.close()


def _claim_next_job() -> "models.ProcessingJob | None":
    """Navbatdagi bitta ishni "processing" deb belgilab, o'zini
    qaytaradi. Bitta jarayon (process) ichida faqat BITTA worker
    tsikli ishlaydi deb faraz qilinadi (bu -- desktop/lokal
    joylashtirish uchun to'g'ri faraz), shuning uchun bu yerda
    alohida "SELECT ... FOR UPDATE" kabi murakkab lock kerak emas."""
    db = SessionLocal()
    try:
        job = (
            db.query(models.ProcessingJob)
            .filter(models.ProcessingJob.status == models.JobStatus.queued)
            .order_by(models.ProcessingJob.created_at.asc())
            .first()
        )
        if not job:
            return None
        job.status = models.JobStatus.processing
        db.commit()
        db.refresh(job)
        db.expunge(job)  # session yopilgandan keyin ham obyektdan foydalanish uchun
        return job
    finally:
        db.close()


def _run_booklet_generation(job: "models.ProcessingJob") -> None:
    from app.services.exam_service import run_exam_generation
    payload = job.payload_json or {}
    paper_variant_count = payload.get("paper_variant_count", 1)
    # run_exam_generation o'zi ichida job.status/progress'ni to'liq
    # boshqaradi (bu funksiya avvaldan shunday yozilgan -- o'zgartirish
    # shart emas, faqat endi uni TO'G'RIDAN-TO'G'RI so'rov ichidan emas,
    # DURABLE worker orqali chaqiramiz).
    run_exam_generation(job.exam_id, job.id, paper_variant_count)


def _run_omr_check(job: "models.ProcessingJob") -> None:
    from app.services.omr_service import run_omr_check_job
    payload = job.payload_json or {}
    run_omr_check_job(
        job_id=job.id,
        file_path=payload["file_path"],
        filename=payload.get("filename", "sheet.pdf"),
        teacher_id=payload.get("teacher_id"),
    )


_JOB_HANDLERS = {
    "booklet_generation": _run_booklet_generation,
    "omr_check": _run_omr_check,
}


def _mark_failed(job_id: str, message: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(models.ProcessingJob, job_id)
        if job:
            job.status = models.JobStatus.failed
            job.error_message = message
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


async def _worker_loop() -> None:
    logger.info("Ish (job) worker tsikli ishga tushdi (poll interval: %ss)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            job = await asyncio.to_thread(_claim_next_job)
            if job is None:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            handler = _JOB_HANDLERS.get(job.kind)
            if handler is None:
                await asyncio.to_thread(_mark_failed, job.id, f"Noma'lum ish turi: {job.kind}")
                continue

            logger.info("Ish boshlandi: %s (%s)", job.id, job.kind)
            try:
                await asyncio.to_thread(handler, job)
                logger.info("Ish yakunlandi: %s (%s)", job.id, job.kind)
            except Exception as e:  # noqa: BLE001
                logger.exception("Ish xato berdi: %s (%s)", job.id, job.kind)
                await asyncio.to_thread(_mark_failed, job.id, str(e))

        except asyncio.CancelledError:
            logger.info("Ish worker tsikli to'xtatildi")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Worker tsiklida kutilmagan xato -- davom etadi")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def start_worker() -> "asyncio.Task":
    """FastAPI lifespan'dan chaqiriladi. Avval qulab qolgan ishlarni
    tiklaydi, so'ng doimiy tsiklni asyncio Task sifatida ishga tushiradi."""
    global _worker_task
    _recover_interrupted_jobs()
    _worker_task = asyncio.create_task(_worker_loop())
    return _worker_task


def stop_worker() -> None:
    if _worker_task is not None:
        _worker_task.cancel()
