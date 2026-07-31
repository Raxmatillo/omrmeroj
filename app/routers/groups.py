# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


from app import models, schemas
from app.database import get_db
from app.deps import require_teacher

router = APIRouter(prefix="/groups", tags=["groups"])


def _get_owned_group(group_id: str, user: models.User, db: Session) -> models.Group:
    group = db.get(models.Group, group_id)
    if not group or group.teacher_id != user.id:
        raise HTTPException(status_code=404, detail="Guruh topilmadi")
    return group


@router.post("", response_model=schemas.GroupOut)
def create_group(payload: schemas.GroupIn, user: models.User = Depends(require_teacher),
                  db: Session = Depends(get_db)):
    group = models.Group(teacher_id=user.id, name=payload.name, description=payload.description)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get("", response_model=list[schemas.GroupOut])
def list_groups(user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    return db.query(models.Group).filter(models.Group.teacher_id == user.id).all()


@router.get("/{group_id}", response_model=schemas.GroupOut)
def get_group(group_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    return _get_owned_group(group_id, user, db)

def _get_owned_student(group_id: str, student_id: str, user: models.User, db: Session) -> models.Student:
    group = _get_owned_group(group_id, user, db)
    student = db.get(models.Student, student_id)
    if not student or student.group_id != group.id:
        raise HTTPException(status_code=404, detail="O'quvchi topilmadi")
    return student

@router.put("/{group_id}", response_model=schemas.GroupOut)
def update_group(group_id: str, payload: schemas.GroupUpdateIn,
                  user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    group = _get_owned_group(group_id, user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}")
def delete_group(group_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    group = _get_owned_group(group_id, user, db)
    try:
        db.delete(group)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Bu guruh bo'yicha imtihon tarixi mavjud -- avval tegishli imtihonlarni o'chiring.",
        )
    return {"ok": True}

@router.post("/{group_id}/students", response_model=schemas.StudentOut)
def add_student(group_id: str, payload: schemas.StudentIn,
                 user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    group = _get_owned_group(group_id, user, db)
    student = models.Student(group_id=group.id, **payload.model_dump())
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


# Ro'yxat bilan qo'shish -- bittadan yuborish o'rniga
@router.post("/{group_id}/students/bulk", response_model=list[schemas.StudentOut])
def add_students_bulk(group_id: str, payload: schemas.StudentBulkIn,
                       user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    group = _get_owned_group(group_id, user, db)
    students = [models.Student(group_id=group.id, **s.model_dump()) for s in payload.students]
    db.add_all(students)
    db.commit()
    for s in students:
        db.refresh(s)
    return students

@router.get("/{group_id}/students", response_model=list[schemas.StudentOut])
def list_students(group_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    group = _get_owned_group(group_id, user, db)
    return group.students


@router.put("/{group_id}/students/{student_id}", response_model=schemas.StudentOut)
def update_student(group_id: str, student_id: str, payload: schemas.StudentUpdateIn,
                    user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    student = _get_owned_student(group_id, student_id, user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(student, field, value)
    db.commit()
    db.refresh(student)
    return student


@router.delete("/{group_id}/students/{student_id}")
def delete_student(group_id: str, student_id: str, hard: bool = False,
                    user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Standart -- soft delete (is_active=False), imtihon tarixi saqlanadi.
    hard=true -- haqiqiy o'chirish (faqat imtihon tarixi bo'lmasa ishlaydi)."""
    student = _get_owned_student(group_id, student_id, user, db)
    if not hard:
        student.is_active = False
        db.commit()
        return {"ok": True, "deactivated": True}
    try:
        db.delete(student)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Bu o'quvchi imtihon tarixiga ega -- hard=true bilan o'chirib bo'lmaydi, deaktivatsiya qiling.",
        )
    return {"ok": True, "deactivated": False}