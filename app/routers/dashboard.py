# -*- coding: utf-8 -*-
"""
Teacher-scoped dashboard statistikasi. Har bir so'rov faqat joriy
o'qituvchiga (require_teacher orqali) tegishli guruh/test/imtihon/natija
ma'lumotlarini qaytaradi -- boshqa o'qituvchilarning ma'lumoti hech qachon
ko'rinmaydi.

MUHIM: Exam modelida `group` va `test_set` deb nomlangan relationship
YO'Q (faqat group_id/test_set_id FK bor) -- shu sababli bu yerda ular
har doim aniq JOIN orqali olinadi, Python attribute sifatida emas
(masalan `exam.test_set` YOZILMAYDI -- bu AttributeError beradi).
Test nomini olish uchun ExamStudent.variant.test_set yo'lidan
foydalanilgan, chunki Variant -> TestSet relationship mavjud va ishonchli.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.deps import require_teacher

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_dashboard_stats(user: models.User = Depends(require_teacher), db: Session = Depends(get_db)):
    teacher_id = user.id

    # ---------- Umumiy sonlar ----------
    groups_count = db.query(models.Group).filter(models.Group.teacher_id == teacher_id).count()

    students_count = (
        db.query(models.Student)
        .join(models.Group, models.Student.group_id == models.Group.id)
        .filter(models.Group.teacher_id == teacher_id, models.Student.is_active.is_(True))
        .count()
    )

    tests_count = db.query(models.TestSet).filter(models.TestSet.teacher_id == teacher_id).count()
    exams_count = db.query(models.Exam).filter(models.Exam.teacher_id == teacher_id).count()

    results_base = (
        db.query(models.Result)
        .join(models.ExamStudent, models.Result.exam_student_id == models.ExamStudent.id)
        .join(models.Exam, models.ExamStudent.exam_id == models.Exam.id)
        .filter(models.Exam.teacher_id == teacher_id)
    )
    results_count = results_base.count()

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_exams_count = (
        db.query(models.Exam)
        .filter(models.Exam.teacher_id == teacher_id, models.Exam.created_at >= today_start)
        .count()
    )

    avg_score_row = results_base.with_entities(func.avg(models.Result.total_score)).scalar()
    avg_score = round(avg_score_row, 2) if avg_score_row is not None else 0.0

    # ---------- Oylik imtihonlar (so'nggi 6 oy) ----------
    six_months_ago = datetime.utcnow() - timedelta(days=180)
    exams_recent = (
        db.query(models.Exam)
        .filter(models.Exam.teacher_id == teacher_id, models.Exam.created_at >= six_months_ago)
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

    # ---------- Barcha natijalar (fanlar + testlar o'rtachasi uchun bir marta olamiz) ----------
    all_results = results_base.all()

    # ---------- Fanlar bo'yicha o'rtacha ball ----------
    subject_scores: dict[str, list[float]] = {}
    for r in all_results:
        for subject, data in (r.per_subject_json or {}).items():
            subject_scores.setdefault(subject, []).append(data.get("score", 0))
    subject_avg = [
        {"subject": s, "avg": round(sum(vals) / len(vals), 2)}
        for s, vals in subject_scores.items()
    ]

    # ---------- Testlar bo'yicha o'rtacha ball (Variant -> TestSet orqali) ----------
    test_scores: dict[str, list[float]] = {}
    for r in all_results:
        variant = r.exam_student.variant if r.exam_student else None
        test_set = variant.test_set if variant else None
        if not test_set:
            continue
        test_scores.setdefault(test_set.name, []).append(r.total_score or 0)
    test_averages = [
        {"name": name, "avg": round(sum(vals) / len(vals), 2)}
        for name, vals in test_scores.items()
    ]

    # ---------- Eng ko'p o'quvchili guruhlar ----------
    top_groups_q = (
        db.query(models.Group.name, func.count(models.Student.id).label("student_count"))
        .join(models.Student, models.Group.id == models.Student.group_id)
        .filter(models.Group.teacher_id == teacher_id, models.Student.is_active.is_(True))
        .group_by(models.Group.id)
        .order_by(func.count(models.Student.id).desc())
        .limit(5)
        .all()
    )
    group_data = [{"name": g.name, "students": g.student_count} for g in top_groups_q]

    # ---------- So'nggi faoliyat: yaratilgan imtihonlar + tekshirilgan natijalar ----------
    recent_exams_q = (
        db.query(models.Exam, models.Group.name.label("group_name"))
        .outerjoin(models.Group, models.Exam.group_id == models.Group.id)
        .filter(models.Exam.teacher_id == teacher_id)
        .order_by(models.Exam.created_at.desc())
        .limit(5)
        .all()
    )
    activities: list[dict] = []
    for exam, group_name in recent_exams_q:
        title = exam.name or exam.exam_code
        activities.append({
            "type": "exam",
            "title": f"Imtihon yaratildi: {title}",
            "group_name": group_name,
            "time": (exam.created_at or datetime.utcnow()).isoformat(),
        })

    recent_results_q = (
        db.query(models.Result, models.Student, models.Group.name.label("group_name"))
        .join(models.ExamStudent, models.Result.exam_student_id == models.ExamStudent.id)
        .join(models.Exam, models.ExamStudent.exam_id == models.Exam.id)
        .join(models.Student, models.ExamStudent.student_id == models.Student.id)
        .outerjoin(models.Group, models.Student.group_id == models.Group.id)
        .filter(models.Exam.teacher_id == teacher_id)
        .order_by(models.Result.checked_at.desc())
        .limit(5)
        .all()
    )
    for result, student, group_name in recent_results_q:
        activities.append({
            "type": "result",
            "title": f"Natija tekshirildi: {student.full_name} ({result.total_score:g} ball)",
            "group_name": group_name,
            "time": (result.checked_at or datetime.utcnow()).isoformat(),
        })

    activities.sort(key=lambda a: a["time"], reverse=True)
    recent_activities = activities[:8]

    return {
        "totals": {
            "groups": groups_count,
            "students": students_count,
            "tests": tests_count,
            "exams": exams_count,
            "results": results_count,
            "today_exams": today_exams_count,
            "avg_score": avg_score,
        },
        "monthly_exams": monthly_data,
        "subject_averages": subject_avg,
        "test_averages": test_averages,
        "top_groups": group_data,
        "recent_activities": recent_activities,
    }