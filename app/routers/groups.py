# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

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


@router.post("/{group_id}/students", response_model=schemas.StudentOut)
def add_student(group_id: str, payload: schemas.StudentIn,
                 user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    group = _get_owned_group(group_id, user, db)
    student = models.Student(group_id=group.id, **payload.model_dump())
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


@router.get("/{group_id}/students", response_model=list[schemas.StudentOut])
def list_students(group_id: str, user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    group = _get_owned_group(group_id, user, db)
    return group.students
