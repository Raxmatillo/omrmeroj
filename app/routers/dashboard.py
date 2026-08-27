# app/routers/dashboard.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from app import models
from app.database import get_db
from app.deps import require_teacher

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_dashboard_stats(
    user: models.User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    # -----------------------------------------------------------------
    # 1) Umumiy sonlar
    # -----------------------------------------------------------------
    groups_count = db.query(models.Group).filter(models.Group.teacher_id == user.id).count()
    students_count = (
        db.query(models.Student)
        .join(models.Group)
        .filter(models.Group.teacher_id == user.id)
        .count()
    )
    tests_count = db.query(models.TestSet).filter(models.TestSet.teacher_id == user.id).count()
    exams_count = db.query(models.Exam).filter(models.Exam.teacher_id == user.id).count()
    results_count = (
        db.query(models.Result)
        .join(models.ExamStudent)
        .join(models.Exam)
        .filter(models.Exam.teacher_id == user.id)
        .count()
    )

    today = datetime.utcnow().date()
    today_exams = (
        db.query(models.Exam)
        .filter(
            models.Exam.teacher_id == user.id,
            models.Exam.status == models.ExamStatus.ready,
            func.date(models.Exam.created_at) == today,
        )
        .count()
    )

    # Group / TestSet uchun relationship yo'q (faqat *_id FK bor),
    # shuning uchun nomlarni ID orqali xaritaga yig'ib olamiz -- bu
    # keyingi joylarda N+1 so'rov qilmaslik uchun ham kerak.
    groups_map = {
        g.id: g.name
        for g in db.query(models.Group).filter(models.Group.teacher_id == user.id).all()
    }
    test_sets_map = {
        t.id: t.name
        for t in db.query(models.TestSet).filter(models.TestSet.teacher_id == user.id).all()
    }

    # -----------------------------------------------------------------
    # 2) Oylik imtihonlar (so'nggi 6 oy)
    # -----------------------------------------------------------------
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
    monthly_exams = [
        {"month": datetime.strptime(k, "%Y-%m").strftime("%b %Y"), "count": v}
        for k, v in sorted(month_counts.items())
    ]

    # -----------------------------------------------------------------
    # 3) Natijalarni BIR MARTA olib, subject/test o'rtachalarini birga
    #    hisoblaymiz (frontendda avval bo'lgani kabi har bir talaba uchun
    #    alohida so'rov yubormaymiz)
    # -----------------------------------------------------------------
    results = (
        db.query(models.Result)
        .join(models.ExamStudent)
        .join(models.Exam)
        .filter(models.Exam.teacher_id == user.id)
        .all()
    )

    subject_scores: dict[str, list[float]] = {}
    test_scores: dict[str, list[float]] = {}

    for r in results:
        # per_subject_json shakli: {"Matematika": {"correct": 5, "total": 10, "score": 4.5}, ...}
        if r.per_subject_json:
            for subject, data in r.per_subject_json.items():
                subject_scores.setdefault(subject, []).append(data.get("score", 0))

        exam = r.exam_student.exam
        test_name = test_sets_map.get(exam.test_set_id, "Noma'lum")
        test_scores.setdefault(test_name, []).append(r.total_score or 0)

    subject_averages = [
        {"subject": s, "avg": round(sum(v) / len(v), 2) if v else 0}
        for s, v in subject_scores.items()
    ]
    test_averages = [
        {"name": n, "avg": round(sum(v) / len(v), 2) if v else 0}
        for n, v in test_scores.items()
    ]

    # -----------------------------------------------------------------
    # 4) Eng ko'p o'quvchili guruhlar
    # -----------------------------------------------------------------
    top_groups_q = (
        db.query(models.Group.name, func.count(models.Student.id).label("student_count"))
        .join(models.Student, models.Group.id == models.Student.group_id)
        .filter(models.Group.teacher_id == user.id)
        .group_by(models.Group.id)
        .order_by(func.count(models.Student.id).desc())
        .limit(5)
        .all()
    )
    top_groups = [{"name": g.name, "students": g.student_count} for g in top_groups_q]

    # -----------------------------------------------------------------
    # 5) So'nggi faoliyat -- oxirgi imtihonlar + oxirgi natijalar birga
    # -----------------------------------------------------------------
    activities: list[dict] = []

    recent_exams = (
        db.query(models.Exam)
        .filter(models.Exam.teacher_id == user.id)
        .order_by(models.Exam.created_at.desc())
        .limit(5)
        .all()
    )
    for e in recent_exams:
        activities.append({
            "type": "exam",
            "title": e.name or f"Imtihon {e.exam_code}",
            "time": e.created_at.isoformat(),
            "group_name": groups_map.get(e.group_id),
        })

    recent_results = (
        db.query(models.Result)
        .join(models.ExamStudent)
        .join(models.Exam)
        .filter(models.Exam.teacher_id == user.id)
        .order_by(models.Result.checked_at.desc())
        .limit(5)
        .all()
    )
    for r in recent_results:
        student = r.exam_student.student
        exam = r.exam_student.exam
        activities.append({
            "type": "result",
            "title": f"{student.full_name if student else 'Talaba'} — {r.total_score:.1f} ball",
            "time": r.checked_at.isoformat(),
            "group_name": groups_map.get(exam.group_id),
        })

    activities.sort(key=lambda a: a["time"], reverse=True)
    recent_activities = activities[:6]

    return {
        "totals": {
            "groups": groups_count,
            "students": students_count,
            "tests": tests_count,
            "exams": exams_count,
            "results": results_count,
            "today_exams": today_exams,
        },
        "monthly_exams": monthly_exams,
        "subject_averages": subject_averages,
        "test_averages": test_averages,
        "top_groups": top_groups,
        "recent_activities": recent_activities,
    }
