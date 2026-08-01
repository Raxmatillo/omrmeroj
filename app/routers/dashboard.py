# app/routers/dashboard.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import datetime, timedelta
from app import models
from app.database import get_db
from app.deps import require_teacher

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/stats")
def get_dashboard_stats(user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    # Umumiy statistikalar
    groups_count = db.query(models.Group).filter(models.Group.teacher_id == user.id).count()
    students_count = db.query(models.Student).join(models.Group).filter(models.Group.teacher_id == user.id).count()
    tests_count = db.query(models.TestSet).filter(models.TestSet.teacher_id == user.id).count()
    exams_count = db.query(models.Exam).filter(models.Exam.teacher_id == user.id).count()
    results_count = db.query(models.Result).join(models.ExamStudent).join(models.Exam).filter(models.Exam.teacher_id == user.id).count()

    # Oylik imtihonlar (so'nggi 6 oy)
    six_months_ago = datetime.utcnow() - timedelta(days=180)
    exams_recent = (
        db.query(models.Exam)
        .filter(models.Exam.teacher_id == user.id, models.Exam.created_at >= six_months_ago)
        .all()
    )
    month_counts: dict[str, int] = {}
    for e in exams_recent:
        key = e.created_at.strftime("%Y-%m")
        month_counts[key] = month_counts.get(key, 0) + 1
    monthly_data = [
        {"month": datetime.strptime(k, "%Y-%m").strftime("%b %Y"), "count": v}
        for k, v in sorted(month_counts.items())
    ]

    # Fanlar bo'yicha o'rtacha ball (barcha natijalar bo'yicha)
    # Murakkabroq, hozircha oddiy variant: har bir natijadan per_subject_json ni o'qiymiz
    results = db.query(models.Result).join(models.ExamStudent).join(models.Exam).filter(
        models.Exam.teacher_id == user.id
    ).all()
    
    subject_scores = {}
    for r in results:
        if r.per_subject_json:
            for subject, data in r.per_subject_json.items():
                subject_scores.setdefault(subject, []).append(data.get("score", 0))

    subject_avg = [
        {"subject": s, "avg": sum(vals)/len(vals) if vals else 0}
        for s, vals in subject_scores.items()
    ]

    # Eng ko'p o'quvchili guruhlar
    top_groups = (
        db.query(
            models.Group.name,
            func.count(models.Student.id).label('student_count')
        )
        .join(models.Student, models.Group.id == models.Student.group_id)
        .filter(models.Group.teacher_id == user.id)
        .group_by(models.Group.id)
        .order_by(func.count(models.Student.id).desc())
        .limit(5)
        .all()
    )
    group_data = [
        {"name": g.name, "students": g.student_count}
        for g in top_groups
    ]

    return {
        "totals": {
            "groups": groups_count,
            "students": students_count,
            "tests": tests_count,
            "exams": exams_count,
            "results": results_count,
        },
        "monthly_exams": monthly_data,
        "subject_averages": subject_avg,
        "top_groups": group_data,
    }