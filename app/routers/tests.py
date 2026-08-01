# -*- coding: utf-8 -*-
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


from app import models, schemas
from app.database import get_db
from app.deps import require_teacher
from app.utils.excel_import import parse_excel, ExcelImportError

router = APIRouter(prefix="/tests", tags=["tests"])


def _get_owned_test_set(test_set_id: str, user: models.User, db: Session) -> models.TestSet:
    ts = db.get(models.TestSet, test_set_id)
    if not ts or ts.teacher_id != user.id:
        raise HTTPException(status_code=404, detail="Test topilmadi")
    return ts


def _get_owned_variant(variant_id: str, user: models.User, db: Session) -> models.Variant:
    variant = db.get(models.Variant, variant_id)
    if not variant:
        raise HTTPException(status_code=404, detail="Variant topilmadi")
    _get_owned_test_set(variant.test_set_id, user, db)  # ownership check
    return variant


# ---------- TestSet ----------

@router.post("", response_model=schemas.TestSetOut)
def create_test_set(payload: schemas.TestSetIn, user: models.User = Depends(require_teacher),
                     db: Session = Depends(get_db)):
    if payload.total_questions not in (30, 45, 60, 90):
        raise HTTPException(status_code=400, detail="total_questions faqat 30/45/60/90 bo'lishi mumkin")
    ts = models.TestSet(teacher_id=user.id, name=payload.name, total_questions=payload.total_questions)
    db.add(ts)
    db.commit()
    db.refresh(ts)
    return ts


@router.get("", response_model=list[schemas.TestSetOut])
def list_test_sets(user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    return db.query(models.TestSet).filter(models.TestSet.teacher_id == user.id).all()


@router.get("/{test_set_id}", response_model=schemas.TestSetOut)
def get_test_set(test_set_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    return _get_owned_test_set(test_set_id, user, db)

@router.put("/{test_set_id}", response_model=schemas.TestSetOut)
def update_test_set(test_set_id: str, payload: schemas.TestSetUpdateIn,
                     user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    ts = _get_owned_test_set(test_set_id, user, db)
    if payload.name is not None:
        ts.name = payload.name
    db.commit()
    db.refresh(ts)
    return ts


@router.delete("/{test_set_id}")
def delete_test_set(test_set_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    ts = _get_owned_test_set(test_set_id, user, db)
    try:
        db.delete(ts)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Bu test asosida imtihon(lar) yaratilgan -- o'chirib bo'lmaydi.")
    return {"ok": True}

# ---------- Variant ----------

@router.post("/{test_set_id}/variants", response_model=schemas.VariantOut)
def create_variant(test_set_id: str, payload: schemas.VariantIn,
                    user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    ts = _get_owned_test_set(test_set_id, user, db)
    variant = models.Variant(test_set_id=ts.id, label=payload.label, order_index=payload.order_index)
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


@router.post("/variants/{variant_id}/duplicate", response_model=schemas.VariantOut)
def duplicate_variant(variant_id: str, new_label: str,
                       user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Bitta variantni nusxalab, tez ikkinchi variant tayyorlash uchun
    (masalan javob variantlari tartibini qo'lda o'zgartirib qayta ishlatish)."""
    src = _get_owned_variant(variant_id, user, db)
    new_variant = models.Variant(test_set_id=src.test_set_id, label=new_label, order_index=src.order_index + 1)
    db.add(new_variant)
    db.flush()
    for q in src.questions:
        db.add(models.Question(
            variant_id=new_variant.id, tartib=q.tartib, fan=q.fan, ball=q.ball,
            savol_html=q.savol_html, savol_rasm_url=q.savol_rasm_url, jadval_html=q.jadval_html,
            variant_a_html=q.variant_a_html, variant_b_html=q.variant_b_html,
            variant_c_html=q.variant_c_html, variant_d_html=q.variant_d_html,
            togri_javob=q.togri_javob,
        ))
    db.commit()
    db.refresh(new_variant)
    return new_variant


@router.delete("/variants/{variant_id}")
def delete_variant(variant_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    variant = _get_owned_variant(variant_id, user, db)
    try:
        db.delete(variant)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Bu variant asosida imtihon(lar) yaratilgan -- o'chirib bo'lmaydi.")
    return {"ok": True}

# ---------- Question ----------

@router.post("/variants/{variant_id}/questions", response_model=schemas.QuestionOut)
def add_question(variant_id: str, payload: schemas.QuestionIn,
                  user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    variant = _get_owned_variant(variant_id, user, db)
    if payload.togri_javob.upper() not in ("A", "B", "C", "D"):
        raise HTTPException(status_code=400, detail="togri_javob faqat A/B/C/D bo'lishi kerak")
    q = models.Question(variant_id=variant.id, **{**payload.model_dump(), "togri_javob": payload.togri_javob.upper()})
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@router.put("/questions/{question_id}", response_model=schemas.QuestionOut)
def update_question(question_id: str, payload: schemas.QuestionIn,
                     user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    q = db.get(models.Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Savol topilmadi")
    _get_owned_variant(q.variant_id, user, db)
    for field, value in payload.model_dump().items():
        setattr(q, field, value.upper() if field == "togri_javob" else value)
    db.commit()
    db.refresh(q)
    return q


@router.post("/variants/{variant_id}/import-excel")
async def import_excel(variant_id: str, file: UploadFile = File(...),
                        user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Tayyor Excel shablonidan tezkor savol qo'shish (oddiy matnli
    savollar uchun -- rasm/formula kerak bo'lsa admin panelda qo'lda
    to'ldiriladi/tahrirlanadi)."""
    
    variant = _get_owned_variant(variant_id, user, db)
    test_set = db.get(models.TestSet, variant.test_set_id)
    if not test_set:
        raise HTTPException(status_code=404, detail="TestSet topilmadi")
    
    content = await file.read()
    try:
        rows = parse_excel(BytesIO(content))
    except ExcelImportError as e:
        raise HTTPException(status_code=400, detail=str(e))


    # MUHIM: Savollar sonini tekshirish
    existing_count = len(variant.questions)
    if existing_count + len(rows) > test_set.total_questions:
        raise HTTPException(
            status_code=400,
            detail=f"Jami savollar soni {test_set.total_questions} dan oshib ketadi. "
                   f"Mavjud: {existing_count}, qo'shilmoqchi: {len(rows)}"
        )
    

    existing_max = max((q.tartib for q in variant.questions), default=0)
    created = []
    for i, row in enumerate(rows, start=1):
        q = models.Question(variant_id=variant.id, tartib=existing_max + i, **row)
        db.add(q)
        created.append(q)
    db.commit()
    return {"added": len(created)}


@router.delete("/questions/{question_id}")
def delete_question(question_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    q = db.get(models.Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Savol topilmadi")
    _get_owned_variant(q.variant_id, user, db)
    db.delete(q)
    db.commit()
    return {"ok": True}
