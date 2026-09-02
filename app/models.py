# -*- coding: utf-8 -*-
import enum
import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum, JSON,
    UniqueConstraint, CheckConstraint,
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
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uid)
    phone = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.teacher, nullable=False)
    full_name = Column(String, nullable=True)
    telegram_id = Column(String, nullable=True, unique=True)
    is_active = Column(Boolean, default=True)
    # Parol saqlangan-u, lekin bot orqali TASDIQLANMAGAN bo'lishi mumkin
    # (register-request bosqichida password_hash yoziladi, lekin
    # register-verify muvaffaqiyatli bo'lgunicha is_verified=False qoladi
    # va login rad etiladi).
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    groups = relationship("Group", back_populates="teacher")
    test_sets = relationship("TestSet", back_populates="teacher")
    exams = relationship("Exam", back_populates="teacher")


class PhoneVerificationCode(Base):
    __tablename__ = "phone_verification_codes"

    id = Column(String, primary_key=True, default=uid)
    phone = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    # "register" | "reset_password" -- bir turdagi kod boshqa maqsadda
    # ishlatilib qolmasligi uchun (masalan registratsiya kodi bilan
    # parol tiklab bo'lmaydi).
    purpose = Column(String, nullable=False, default="register")
    attempts = Column(Integer, default=0, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)


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
    savol_rasm_style = Column(String, default="medium")  # small, medium, large, original

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
    # ESKI tizim uchun (Variant asosidagi imtihon). YANGI (Toplam
    # asosidagi) imtihon uchun bu None bo'ladi, o'rniga toplam_id
    # to'ldiriladi -- ikkalasidan FAQAT BITTASI bo'lishi kerak
    # (app/services/exam_service.py'dagi create_exam_job /
    # create_toplam_exam_job shu shartni ta'minlaydi).
    test_set_id = Column(String, ForeignKey("test_sets.id"), nullable=True)
    # YANGI: Savollar banki -- Toplam asosidagi imtihon uchun.
    toplam_id = Column(String, ForeignKey("toplamlar.id"), nullable=True)

    name = Column(String, nullable=True)  # foydalanuvchi kiritadi

    exam_code = Column(String, unique=True, nullable=False)  # "EX-4F7A2C" -- botga/UI'ga ko'rsatiladi
    total_questions = Column(Integer, nullable=False)
    status = Column(Enum(ExamStatus), default=ExamStatus.draft)
    zip_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # 7 kundan keyin auto-delete uchun
    public_checking = Column(Boolean, default=False, nullable=False)

    teacher = relationship("User", back_populates="exams")
    students = relationship("ExamStudent", back_populates="exam", cascade="all, delete-orphan")
    toplam = relationship("Toplam")  # YANGI -- faqat toplam_id berilgan bo'lsa to'ldiriladi


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
    variant_id = Column(String, ForeignKey("variants.id"), nullable=True)  # YANGI: Toplam asosidagi imtihonlarda None

    booklet_id = Column(String(7), unique=True, nullable=False, index=True)
    # app/omr/generate_question_booklet.py -> build() qaytargan format bilan BIR XIL:
    # {tartib: {"fan": ..., "ball": ..., "correct_letter_shown_to_student": "B",
    #           "letter_to_original_option": {...}}}
    # app/services/omr_service.py aynan shu maydon nomlarini kutadi.
    paper_variant_number = Column(Integer, nullable=True)

    answer_key_json = Column(JSON, nullable=False)

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

    raw_answers_json = Column(JSON, nullable=False)
    correct_count = Column(Integer, default=0)
    incorrect_count = Column(Integer, default=0)
    blank_count = Column(Integer, default=0)
    ambiguous_count = Column(Integer, default=0)
    total_score = Column(Float, default=0)
    per_subject_json = Column(JSON, default=dict)

    # YANGI: talaba javob varag'ida belgilagan TEST VARIANTI kitobchada
    # unga tayinlangan variant bilan mos kelmasa True (masalan boshqa
    # talabaning kitobchasidan foydalangan bo'lishi mumkin).
    detected_paper_variant = Column(Integer, nullable=True)
    variant_mismatch = Column(Boolean, default=False)

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
    # YANGI: durable job_worker.py uchun -- ishga kerakli qo'shimcha
    # ma'lumot (masalan paper_variant_count, file_path, teacher_id) va
    # necha marta qayta urinilgani (server qulab, "processing"da qolib
    # ketgan ishlarni tiklashda ishlatiladi).
    payload_json = Column(JSON, nullable=True)
    attempts = Column(Integer, default=0, nullable=False)



class ServiceRequestStatus(str, enum.Enum):
    pending = "pending"          # kutilmoqda
    in_progress = "in_progress"  # jarayonda
    done = "done"                # tayyor
    cancelled = "cancelled"      # bekor qilingan


class PaymentStatus(str, enum.Enum):
    unpaid = "unpaid"
    paid = "paid"


class ServiceRequest(Base):
    """
    Mijoz botga /buyurtma orqali yozgan so'rovi -- masalan "90 ta savol
    tayyorlab bering, fanlar: matematika, fizika" kabi erkin matnli
    tavsif. Bu -- to'liq avtomatlashtirilgan tizim emas, balki SIZ
    (admin) qo'lda ko'rib chiqib bajaradigan buyurtmalar navbati.
    """
    __tablename__ = "service_requests"

    id = Column(String, primary_key=True, default=uid)

    # So'rov yuborgan kishi -- User jadvaliga BOG'LANMAGAN ataylab,
    # chunki so'rov yuboruvchi hali ro'yxatdan o'tmagan bo'lishi mumkin
    # (masalan potentsial yangi mijoz, hali teacher akkaunti yo'q).
    telegram_id = Column(String, nullable=False, index=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)

    description = Column(Text, nullable=False)

    status = Column(Enum(ServiceRequestStatus), default=ServiceRequestStatus.pending, nullable=False)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.unpaid, nullable=False)

    admin_note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)


# ============================================================
# 1. SAVOLLAR BANKI
# ============================================================

# ============================================================
# 0. FAN (Subject) -- oldindan ro'yxatdan o'tkaziladigan fanlar ro'yxati
#
# MUHIM: bu ESKI tizimdagi Question.fan (erkin matn) bilan
# ALOQADOR EMAS -- faqat YANGI (bank) tizimi uchun. O'qituvchi
# savol qo'shishdan OLDIN fanni bir marta ro'yxatdan o'tkazadi
# (masalan "Matematika"), keyin har bir savolda shu fanni TANLAYDI
# (erkin matn kiritmaydi) -- shu orqali "Matematika"/"matematika"/
# "MATEMATIKA" kabi yozuv xilma-xilligi (va shundan kelib chiqadigan
# statistika bo'linib ketishi) oldini olinadi.
# ============================================================
class Fan(Base):
    __tablename__ = "fans"
    __table_args__ = (
        UniqueConstraint("teacher_id", "name", name="uq_fan_teacher_name"),
    )

    id = Column(String, primary_key=True, default=uid)
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class QuestionBankItem(Base):
    """
    Mustaqil savol -- hech qanday Variant/TestSet'ga BOG'LANMAGAN.
    Bitta o'qituvchi tomonidan yaratiladi, keyin istalgan sonli
    Toplam'ga (ToplamQuestion orqali) qo'shilishi mumkin.
    """
    __tablename__ = "question_bank_items"

    id = Column(String, primary_key=True, default=uid)
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # YANGI: erkin matn ("fan = Column(String)") o'rniga Fan jadvaliga
    # HAVOLA -- o'qituvchi fanni oldindan ro'yxatdan o'tkazadi, savol
    # qo'shishda shundan TANLAYDI.
    fan_id = Column(String, ForeignKey("fans.id"), nullable=False, index=True)
    fan = relationship("Fan")

    # YANGI (pptx'dagi g'oya): manba ma'lumotlari -- qaysi kitobdan,
    # qaysi bo'limdan ko'chirilgani. Ixtiyoriy, lekin qidiruv/filter
    # uchun juda foydali.
    kitob_nomi = Column(String, nullable=True, index=True)
    bolim_nomi = Column(String, nullable=True, index=True)

    savol_html = Column(Text, nullable=False)
    savol_rasm_url = Column(String, nullable=True)
    savol_rasm_style = Column(String, default="medium")
    jadval_html = Column(Text, nullable=True)

    variant_a_html = Column(Text, nullable=False)
    variant_b_html = Column(Text, nullable=False)
    variant_c_html = Column(Text, nullable=False)
    variant_d_html = Column(Text, nullable=False)
    togri_javob = Column(String(1), nullable=False)  # "A"|"B"|"C"|"D"

    # Standart/tavsiya etilgan ball -- Toplam'ga qo'shilganda
    # ToplamQuestion.ball orqali BEKOR QILINISHI (override) mumkin.
    ball = Column(Float, nullable=False, default=1.1)

    # --- Qiyinchilik statistikasi (DENORMALIZATSIYA -- yuqoridagi
    #     izohga qarang) ---
    times_shown = Column(Integer, default=0, nullable=False)
    times_correct = Column(Integer, default=0, nullable=False)
    # None = hali baholanmagan (kamida 1 marta imtihonda ishlatilib,
    # tekshirilmagan). UI'da "baholanmagan" alohida ko'rsatilishi kerak.
    difficulty_percent = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    teacher = relationship("User")


# ============================================================
# 2. TO'PLAM (Variant/TestSet o'rnini bosuvchi, ularni o'chirmaydi)
# ============================================================

class Toplam(Base):
    """
    "Tayyor test" -- bir nechta QuestionBankItem'dan yig'ilgan,
    imtihon yaratishda to'g'ridan-to'g'ri ishlatiladigan konteyner.
    Eski Variant'dan farqi: savollar bu yerda "yashamaydi", faqat
    ULARGA HAVOLA qilinadi (ToplamQuestion orqali) -- shuning uchun
    bitta savol ko'p to'plamda qayta ishlatilishi mumkin.
    """
    __tablename__ = "toplamlar"
    __table_args__ = (
        # YANGI: to'plam ko'pi bilan 90 ta savoldan iborat bo'lishi
        # kerak (DTM-uslubidagi eng katta imtihon hajmi). Bu -- ikkinchi
        # himoya qatlami (birinchisi schemas.ToplamIn'dagi Field(le=90)
        # va bank_service.create_toplam'dagi tekshiruv) -- baza
        # darajasida ham noto'g'ri qiymat yozilishini butunlay
        # istisno qiladi (masalan kelajakda boshqa yo'l bilan --
        # migratsiya skripti, to'g'ridan-to'g'ri SQL orqali -- yozilsa
        # ham).
        CheckConstraint("savollar_soni > 0 AND savollar_soni <= 90", name="ck_toplam_savollar_soni_max90"),
    )

    id = Column(String, primary_key=True, default=uid)
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    savollar_soni = Column(Integer, nullable=False)  # 30/45/60/90 (rejalashtirilgan hajm)

    # YANGI: avtomatik to'ldirish uchun ishlatilgan qiyinchilik
    # maqsadi -- faqat ma'lumot/qayta hosil qilish uchun saqlanadi,
    # majburiy emas (qo'lda ham to'ldirish mumkin).
    # Masalan: {"oson": 30, "ortacha": 50, "qiyin": 20} (foizlarda)
    qiyinchilik_maqsadi_json = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    teacher = relationship("User")
    items = relationship(
        "ToplamQuestion", back_populates="toplam",
        order_by="ToplamQuestion.tartib", cascade="all, delete-orphan",
    )

    @property
    def question_count(self) -> int:
        return len(self.items)


class ToplamQuestion(Base):
    """
    Toplam <-> QuestionBankItem ko'p-ko'pga bog'lanishi.

    MUHIM: `tartib` va `ball` shu BITTA bog'lanishga tegishli -- bir
    xil savol ikkinchi to'plamda BOSHQA tartib raqami va/yoki BOSHQA
    ball bilan qatnashishi mumkin (masalan bank'dagi standart ball
    1.1 bo'lsa-yu, muayyan to'plamda 3.1 sifatida ishlatilishi kerak
    bo'lsa).
    """
    __tablename__ = "toplam_questions"

    id = Column(String, primary_key=True, default=uid)
    toplam_id = Column(String, ForeignKey("toplamlar.id"), nullable=False, index=True)
    bank_item_id = Column(String, ForeignKey("question_bank_items.id"), nullable=False, index=True)

    tartib = Column(Integer, nullable=False)  # 1..N -- javoblar varag'idagi ustun raqami
    ball = Column(Float, nullable=False)       # shu to'plamdagi ball (bank'dagi standartdan farqli bo'lishi mumkin)

    toplam = relationship("Toplam", back_populates="items")
    bank_item = relationship("QuestionBankItem")


# ============================================================
# 3. SAVOL TARIXI (QuestionAttempt) -- YANGILANGAN VERSIYA
#
# Eslatma: agar avvalgi patch orqali app/models.py'ga oddiyroq
# QuestionAttempt klassi qo'shgan bo'lsangiz (faqat `question_id`
# bilan, `bank_item_id`siz) -- ALBATTA O'SHANI shu bilan
# ALMASHTIRING, ikkalasini birga qoldirmang (nomlar to'qnashadi).
# Agar hali umuman qo'shmagan bo'lsangiz -- shunchaki shuni qo'shing.
# ============================================================

class QuestionAttempt(Base):
    """
    Bitta talabaning bitta savolga bergan javobi haqidagi yozuv --
    qiyinchilik statistikasi (va kelajakda Rasch metodi) uchun xom
    ma'lumot.

    MUHIM: `question_id` va `bank_item_id`dan FAQAT BITTASI
    to'ldiriladi -- qaysi savol ESKI (Variant->Question) tizimidanmi
    yoki YANGI (Savollar banki)danmi, shunga qarab.
    """
    __tablename__ = "question_attempts"

    id = Column(String, primary_key=True, default=uid)

    # ESKI tizim uchun (ixtiyoriy)
    question_id = Column(String, ForeignKey("questions.id"), nullable=True, index=True)
    # YANGI tizim uchun (ixtiyoriy)
    bank_item_id = Column(String, ForeignKey("question_bank_items.id"), nullable=True, index=True)

    exam_student_id = Column(String, ForeignKey("exam_students.id"), nullable=False, index=True)

    given_letter = Column(String(1), nullable=True)  # "A"/"B"/"C"/"D", bo'sh bo'lsa None
    # None = bo'sh yoki noaniq (statistikaga qo'shilmaydi)
    is_correct = Column(Boolean, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    question = relationship("Question")
    bank_item = relationship("QuestionBankItem")
    exam_student = relationship("ExamStudent")