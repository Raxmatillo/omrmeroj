# -*- coding: utf-8 -*-
"""
SAVOLLAR BANKI ARXITEKTURASI -- 3-QISM: API ROUTER

Bu fayl app/services/bank_service.py (2-qism)ni HTTP orqali ochadi.
Uslub va auth naqshi app/routers/groups.py bilan bir xil.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.deps import require_teacher
from app.services import bank_service as bs
from app.services.exam_service import (
    ExamServiceError,
    create_toplam_exam_job,
    run_toplam_exam_generation,
)

router = APIRouter(prefix="/bank", tags=["question-bank"])


# =============================================================
# QuestionBankItem
# =============================================================

@router.post("/questions", response_model=schemas.BankItemOut)
def create_question(
    payload: schemas.BankItemIn,
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    try:
        return bs.create_bank_item(db, teacher_id=user.id, **payload.model_dump())
    except bs.BankServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/questions", response_model=schemas.BankSearchOut)
def search_questions(
    fan: str | None = None,
    kitob_nomi: str | None = None,
    bolim_nomi: str | None = None,
    search_text: str | None = None,
    difficulty_min: float | None = None,
    difficulty_max: float | None = None,
    only_unrated: bool = False,
    limit: int = 50,
    offset: int = 0,
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    result = bs.search_bank_items(
        db, teacher_id=user.id, fan=fan, kitob_nomi=kitob_nomi, bolim_nomi=bolim_nomi,
        search_text=search_text, difficulty_min=difficulty_min, difficulty_max=difficulty_max,
        only_unrated=only_unrated, limit=limit, offset=offset,
    )
    return {"items": result.items, "total": result.total}


@router.get("/sources")
def get_sources(user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Frontend filter dropdown'lari uchun -- mavjud fan/kitob/bo'lim ro'yxati."""
    return bs.list_distinct_sources(db, teacher_id=user.id)


@router.get("/questions/{item_id}", response_model=schemas.BankItemOut)
def get_question(item_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    try:
        return bs.get_bank_item(db, item_id, teacher_id=user.id)
    except bs.BankServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/questions/{item_id}", response_model=schemas.BankItemOut)
def update_question(
    item_id: str, payload: schemas.BankItemUpdateIn,
    user: models.User = Depends(require_teacher), db: Session = Depends(get_db),
):
    try:
        return bs.update_bank_item(db, item_id, teacher_id=user.id, **payload.model_dump(exclude_unset=True))
    except bs.BankServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/questions/{item_id}")
def delete_question(item_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    try:
        bs.delete_bank_item(db, item_id, teacher_id=user.id)
    except bs.BankServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.post("/questions/recompute-difficulty")
def recompute_all(user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Barcha savollar statistikasini QuestionAttempt yozuvlaridan qayta hisoblaydi."""
    count = bs.recompute_all_difficulties(db, teacher_id=user.id)
    return {"recomputed_count": count}


# =============================================================
# Toplam
# =============================================================

def _toplam_detail(toplam: models.Toplam) -> dict:
    """models.Toplam -> schemas.ToplamDetailOut uchun mos dict.
    (relationship nomi `items`, lekin javobda `questions` deb
    beriladi -- frontend'da tabiiyroq)."""
    return {
        "id": toplam.id, "name": toplam.name, "savollar_soni": toplam.savollar_soni,
        "qiyinchilik_maqsadi_json": toplam.qiyinchilik_maqsadi_json,
        "created_at": toplam.created_at,
        "questions": sorted(toplam.items, key=lambda link: link.tartib),
    }


@router.post("/toplamlar", response_model=schemas.ToplamOut)
def create_toplam_endpoint(
    payload: schemas.ToplamIn,
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    return bs.create_toplam(db, teacher_id=user.id, name=payload.name, savollar_soni=payload.savollar_soni)


@router.get("/toplamlar", response_model=list[schemas.ToplamOut])
def list_toplamlar_endpoint(user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    return bs.list_toplamlar(db, teacher_id=user.id)


@router.get("/toplamlar/{toplam_id}", response_model=schemas.ToplamDetailOut)
def get_toplam_endpoint(toplam_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    try:
        toplam = bs.get_toplam(db, toplam_id, teacher_id=user.id)
    except bs.BankServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _toplam_detail(toplam)


@router.delete("/toplamlar/{toplam_id}")
def delete_toplam_endpoint(toplam_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    try:
        bs.delete_toplam(db, toplam_id, teacher_id=user.id)
    except bs.BankServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.post("/toplamlar/{toplam_id}/questions")
def add_question_endpoint(
    toplam_id: str, payload: schemas.AddQuestionToToplamIn,
    user: models.User = Depends(require_teacher), db: Session = Depends(get_db),
):
    try:
        bs.add_question_to_toplam(
            db, toplam_id, payload.bank_item_id, teacher_id=user.id,
            tartib=payload.tartib, ball=payload.ball,
        )
    except bs.BankServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.delete("/toplamlar/{toplam_id}/questions/{bank_item_id}")
def remove_question_endpoint(
    toplam_id: str, bank_item_id: str,
    user: models.User = Depends(require_teacher), db: Session = Depends(get_db),
):
    try:
        bs.remove_question_from_toplam(db, toplam_id, bank_item_id, teacher_id=user.id)
    except bs.BankServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.put("/toplamlar/{toplam_id}/reorder")
def reorder_endpoint(
    toplam_id: str, payload: schemas.ReorderToplamIn,
    user: models.User = Depends(require_teacher), db: Session = Depends(get_db),
):
    try:
        bs.reorder_toplam_questions(db, toplam_id, teacher_id=user.id, tartib_map=payload.tartib_map)
    except bs.BankServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.put("/toplamlar/{toplam_id}/questions/{bank_item_id}/ball")
def update_ball_endpoint(
    toplam_id: str, bank_item_id: str, payload: schemas.UpdateToplamBallIn,
    user: models.User = Depends(require_teacher), db: Session = Depends(get_db),
):
    try:
        bs.update_toplam_question_ball(db, toplam_id, bank_item_id, teacher_id=user.id, ball=payload.ball)
    except bs.BankServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.post("/toplamlar/{toplam_id}/auto-fill", response_model=schemas.AutoFillOut)
def auto_fill_endpoint(
    toplam_id: str, payload: schemas.AutoFillIn,
    user: models.User = Depends(require_teacher), db: Session = Depends(get_db),
):
    try:
        report = bs.auto_fill_toplam(
            db, toplam_id, teacher_id=user.id, fan=payload.fan,
            qiyinchilik_maqsadi=payload.qiyinchilik_maqsadi,
        )
    except bs.BankServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "added_count": len(report.added),
        "shortfall": report.shortfall,
        "used_unrated_fallback": report.used_unrated_fallback,
    }


@router.post("/toplamlar/{toplam_id}/exams", response_model=schemas.ExamOut)
def create_exam_from_toplam_endpoint(
    toplam_id: str, payload: schemas.CreateToplamExamIn, background_tasks: BackgroundTasks,
    user: models.User = Depends(require_teacher), db: Session = Depends(get_db),
):
    """Toplam asosida imtihon yaratadi -- eski POST /exams'ning
    Toplam-varianti (u O'ZGARTIRILMAGAN, alohida ishlayveradi)."""
    try:
        exam, job = create_toplam_exam_job(
            db, teacher=user, group_id=payload.group_id, toplam_id=toplam_id, name=payload.name,
        )
    except ExamServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))

    background_tasks.add_task(run_toplam_exam_generation, exam.id, job.id)
    return exam
