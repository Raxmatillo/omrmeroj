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
    monthly_exams = (
        db.query(
            func.date_trunc('month', models.Exam.created_at).label('month'),
            func.count(models.Exam.id).label('count')
        )
        .filter(models.Exam.teacher_id == user.id)
        .filter(models.Exam.created_at >= six_months_ago)
        .group_by('month')
        .order_by('month')
        .all()
    )
    monthly_data = [
        {"month": m.month.strftime("%b %Y"), "count": m.count}
        for m in monthly_exams
    ]

    # Fanlar bo'yicha o'rtacha ball (barcha natijalar bo'yicha)
    # Murakkabroq, hozircha oddiy variant: har bir natijadan per_subject_json ni o'qiymiz
    results = db.query(models.Result).join(models.ExamStudent).join(models.Exam).filter(
        models.Exam.teacher_id == user.id
    ).all()
    
    subject_scores = {}
    for r in results:
        if r.per_subject_json:
            for subject, score in r.per_subject_json.items():
                if subject not in subject_scores:
                    subject_scores[subject] = []
                subject_scores[subject].append(score)
    
    subject_avg = [
        {"subject": s, "avg": sum(vals)/len(vals) if vals else 0}
        for s, vals in subject_scores.items()
    ]
    subject_avg.sort(key=lambda x: x["avg"], reverse=True)

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