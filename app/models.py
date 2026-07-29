# -*- coding: utf-8 -*-
import enum
import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum, JSON
)
from sqlalchemy.orm import relationship

from app.database import Base


def uid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    superadmin = "superadmin"
    teacher = "teacher"


class User(Base):
    """
    Teacher yoki superadmin. Telegram orqali ro'yxatdan o'tish keyin
    ulanadi -- hozircha DEV_MODE orqali to'g'ridan-to'g'ri yaratiladi.
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uid)
    phone = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.teacher, nullable=False)
    full_name = Column(String, nullable=True)
    telegram_id = Column(String, nullable=True, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    groups = relationship("Group", back_populates="teacher")
    test_sets = relationship("TestSet", back_populates="teacher")
    exams = relationship("Exam", back_populates="teacher")


# ---------------------------------------------------------------------------
# GURUHLAR
# ---------------------------------------------------------------------------

class Group(Base):
    __tablename__ = "groups"

    id = Column(String, primary_key=True, default=uid)
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    teacher = relationship("User", back_populates="groups")
    students = relationship("Student", back_populates="group", cascade="all, delete-orphan")


class Student(Base):
    __tablename__ = "students"

    id = Column(String, primary_key=True, default=uid)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    middle_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("Group", back_populates="students")

    @property
    def full_name(self):
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# TESTLAR: TestSet -> Variant -> Question
# ---------------------------------------------------------------------------

class TestSet(Base):
    """Bitta 'test' -- masalan '9-sinf yakuniy nazorat'. Bir nechta
    Variant'ga ega bo'ladi (1-variant, 2-variant, ...)."""
    __tablename__ = "test_sets"

    id = Column(String, primary_key=True, default=uid)
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    total_questions = Column(Integer, nullable=False)  # 30/45/60/90
    created_at = Column(DateTime, default=datetime.utcnow)

    teacher = relationship("User", back_populates="test_sets")
    variants = relationship("Variant", back_populates="test_set", cascade="all, delete-orphan")


class Variant(Base):
    """'1-variant', '2-variant' ... -- har biri to'liq mustaqil savollar
    to'plami va tayyor bitta booklet PDF'ga ega bo'ladi."""
    __tablename__ = "variants"

    id = Column(String, primary_key=True, default=uid)
    test_set_id = Column(String, ForeignKey("test_sets.id"), nullable=False)
    label = Column(String, nullable=False)  # "1-variant"
    order_index = Column(Integer, default=0)

    test_set = relationship("TestSet", back_populates="variants")
    questions = relationship(
        "Question", back_populates="variant",
        order_by="Question.tartib", cascade="all, delete-orphan",
    )


class Question(Base):
    """
    savol_html / variant_x_html -- TipTap admin panelidan keladigan HTML
    (LaTeX $...$ ko'rinishida ichida bo'lishi mumkin, KaTeX bilan render
    qilinadi). savol_rasm_url -- Supabase Storage'dagi rasm manzili.
    """
    __tablename__ = "questions"

    id = Column(String, primary_key=True, default=uid)
    variant_id = Column(String, ForeignKey("variants.id"), nullable=False)
    tartib = Column(Integer, nullable=False)  # 1..N -- javoblar varag'idagi ustun raqami
    fan = Column(String, nullable=False)
    ball = Column(Float, nullable=False)

    savol_html = Column(Text, nullable=False)
    savol_rasm_url = Column(String, nullable=True)
    jadval_html = Column(Text, nullable=True)

    variant_a_html = Column(Text, nullable=False)
    variant_b_html = Column(Text, nullable=False)
    variant_c_html = Column(Text, nullable=False)
    variant_d_html = Column(Text, nullable=False)
    togri_javob = Column(String(1), nullable=False)  # "A" | "B" | "C" | "D"

    variant = relationship("Variant", back_populates="questions")


# ---------------------------------------------------------------------------
# IMTIHONLAR
# ---------------------------------------------------------------------------

class ExamStatus(str, enum.Enum):
    draft = "draft"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class Exam(Base):
    __tablename__ = "exams"

    id = Column(String, primary_key=True, default=uid)
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False)
    test_set_id = Column(String, ForeignKey("test_sets.id"), nullable=False)

    exam_code = Column(String, unique=True, nullable=False)  # "EX-4F7A2C" -- botga/UI'ga ko'rsatiladi
    total_questions = Column(Integer, nullable=False)
    status = Column(Enum(ExamStatus), default=ExamStatus.draft)
    zip_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # 7 kundan keyin auto-delete uchun

    teacher = relationship("User", back_populates="exams")
    students = relationship("ExamStudent", back_populates="exam", cascade="all, delete-orphan")


class ExamStudent(Base):
    """
    Har bir talaba + shu imtihondagi javoblar varag'i o'rtasidagi bog'lanish.
    booklet_id -- QR kodga yoziladigan 7 xonali raqam (Booklet ID / Savol ID).
    answer_key_json -- MUHIM: tekshirishning "source of truth"i. Har bir
    savol raqami uchun {qaysi harf qaysi asl variantga mos, to'g'ri harf}.
    """
    __tablename__ = "exam_students"

    id = Column(String, primary_key=True, default=uid)
    exam_id = Column(String, ForeignKey("exams.id"), nullable=False)
    student_id = Column(String, ForeignKey("students.id"), nullable=False)
    variant_id = Column(String, ForeignKey("variants.id"), nullable=False)

    booklet_id = Column(String(7), unique=True, nullable=False, index=True)
    answer_key_json = Column(JSON, nullable=False)  # {tartib: {"togri_harf": "B", "letter_map": {...}}}

    booklet_pdf_path = Column(String, nullable=True)
    answer_sheet_pdf_path = Column(String, nullable=True)

    exam = relationship("Exam", back_populates="students")
    student = relationship("Student")
    variant = relationship("Variant")
    result = relationship("Result", back_populates="exam_student", uselist=False)


# ---------------------------------------------------------------------------
# NATIJALAR
# ---------------------------------------------------------------------------

class ResultStatus(str, enum.Enum):
    ok = "ok"
    needs_review = "needs_review"  # QR o'qilmadi / noaniq bubble bor


class Result(Base):
    __tablename__ = "results"

    id = Column(String, primary_key=True, default=uid)
    exam_student_id = Column(String, ForeignKey("exam_students.id"), unique=True, nullable=False)

    raw_answers_json = Column(JSON, nullable=False)  # {tartib: "A"|None|"MULTI"}
    correct_count = Column(Integer, default=0)
    incorrect_count = Column(Integer, default=0)
    blank_count = Column(Integer, default=0)
    ambiguous_count = Column(Integer, default=0)
    total_score = Column(Float, default=0)
    per_subject_json = Column(JSON, default=dict)

    status = Column(Enum(ResultStatus), default=ResultStatus.ok)
    result_pdf_path = Column(String, nullable=True)
    checked_at = Column(DateTime, default=datetime.utcnow)

    exam_student = relationship("ExamStudent", back_populates="result")


# ---------------------------------------------------------------------------
# BACKGROUND JOB (hozircha sinxron bajariladi, keyin Celery/ARQ ulanadi)
# ---------------------------------------------------------------------------

class JobStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(String, primary_key=True, default=uid)
    kind = Column(String, nullable=False)  # "booklet_generation" | "omr_check"
    exam_id = Column(String, ForeignKey("exams.id"), nullable=True)
    status = Column(Enum(JobStatus), default=JobStatus.queued)
    progress = Column(Integer, default=0)  # 0-100
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
