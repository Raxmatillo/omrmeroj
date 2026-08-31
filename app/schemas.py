# -*- coding: utf-8 -*-
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator, Field

from app.utils.phone import validate_uzbek_phone


# ---------- AUTH ----------

class RegisterRequestIn(BaseModel):
    """Saytda 'Ro'yxatdan o'tish' formasi: telefon + parol + F.I.Sh."""
    phone: str
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=3, max_length=50)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_uzbek_phone(v)


class RegisterVerifyIn(BaseModel):
    phone: str
    code: str = Field(..., min_length=4, max_length=6)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_uzbek_phone(v)


class LoginIn(BaseModel):
    phone: str
    password: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_uzbek_phone(v)


class ForgotPasswordIn(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_uzbek_phone(v)


class ResetPasswordIn(BaseModel):
    phone: str
    code: str = Field(..., min_length=4, max_length=6)
    new_password: str = Field(..., min_length=6)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_uzbek_phone(v)


class RequestCodeOut(BaseModel):
    sent: bool
    detail: str


class ChangePhoneRequestIn(BaseModel):
    new_phone: str

    @field_validator("new_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_uzbek_phone(v)


class ChangePhoneVerifyIn(BaseModel):
    new_phone: str
    code: str = Field(..., min_length=4, max_length=6)

    @field_validator("new_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_uzbek_phone(v)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    phone: str
    full_name: str | None
    role: str
    is_verified: bool


# ---------- GURUHLAR ----------

class StudentIn(BaseModel):
    first_name: str
    last_name: str
    middle_name: str | None = None


class StudentOut(StudentIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    is_active: bool


class GroupIn(BaseModel):
    name: str
    description: str | None = None


class GroupOut(GroupIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    students: list[StudentOut] = []


class GroupUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None


class StudentUpdateIn(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    is_active: bool | None = None


class StudentBulkIn(BaseModel):
    students: list[StudentIn] = Field(..., min_length=1, max_length=200)


# ---------- TESTLAR ----------

class TestSetUpdateIn(BaseModel):
    name: str | None = None


class QuestionIn(BaseModel):
    tartib: int
    fan: str
    ball: float
    savol_html: str
    savol_rasm_url: str | None = None
    savol_rasm_style: str | None = "medium"
    jadval_html: str | None = None
    variant_a_html: str
    variant_b_html: str
    variant_c_html: str
    variant_d_html: str
    togri_javob: str


class QuestionOut(QuestionIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    savol_rasm_style: str | None


# app/schemas.py

class QuestionAnswerDetail(BaseModel):
    question: int
    fan: str
    ball: float
    given: str | None
    correct_letter: str
    status: str  # "correct" | "incorrect" | "blank" | "ambiguous"
    savol_html: str | None = None  # qo'shildi
    variant_a_html: str | None = None  # qo'shildi
    variant_b_html: str | None = None  # qo'shildi
    variant_c_html: str | None = None  # qo'shildi
    variant_d_html: str | None = None  # qo'shildi


class VariantIn(BaseModel):
    label: str
    order_index: int = 0


class VariantOut(VariantIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    questions: list[QuestionOut] = []


class TestSetIn(BaseModel):
    name: str
    total_questions: int


class TestSetOut(TestSetIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    variants: list[VariantOut] = []


# ---------- IMTIHONLAR ----------

class ExamCreateIn(BaseModel):
    name: str | None = Field(None, max_length=100)  # YANGI
    group_id: str
    test_set_id: str
    # Nechta TEST VARIANTI (1..4) ishlatilishi -- app/omr/answer_sheet_generator.py
    # dagi MAX_PAPER_VARIANTS bilan chegaralangan. 1 bo'lsa -- hammaga bir xil
    # (variant belgilash shart emas, booklet_html_generator variant_number=None
    # bo'lganda variant box'ni umuman chizmaydi).
    paper_variant_count: int = Field(default=1, ge=1, le=4)


class ExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str | None  # YANGI
    exam_code: str
    group_id: str
    test_set_id: str | None  # YANGI: Toplam-asosidagi imtihonda None
    toplam_id: str | None = None  # YANGI (Savollar banki)
    total_questions: int
    status: str
    created_at: datetime
    expires_at: datetime | None
    public_checking: bool


# ---------- NATIJA TAFSILOTI / QO'LDA TUZATISH ----------

class ResultDetailOut(BaseModel):
    id: str
    student: str
    correct_count: int
    incorrect_count: int
    blank_count: int
    ambiguous_count: int
    total_score: float
    per_subject: dict
    status: str
    has_pdf: bool
    variant_mismatch: bool
    detected_paper_variant: int | None
    expected_paper_variant: int | None
    questions: list[QuestionAnswerDetail]


class ManualCorrectionIn(BaseModel):
    # {"15": "A", "24": null} -- savol raqami -> to'g'ri harf (yoki bo'sh/aniqlanmagan uchun null)
    corrections: dict[str, str | None]


# ---------- PROFIL ----------

class ProfileUpdateIn(BaseModel):
    full_name: str | None = None


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


class CancelCodeIn(BaseModel):
    phone: str
    purpose: str  # "register", "reset_password", "change_phone", "delete_account"


class DeleteAccountConfirmIn(BaseModel):
    code: str = Field(..., min_length=4, max_length=6, description="Tasdiqlash kodi")


# =============================================================
# YANGI (Savollar banki, 3-qism + fikr-mulohaza asosida yangilangan)
# =============================================================

class FanIn(BaseModel):
    name: str


class FanUpdateIn(BaseModel):
    name: str


class FanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    created_at: datetime


class BankItemIn(BaseModel):
    fan_id: str
    kitob_nomi: str | None = None
    bolim_nomi: str | None = None
    savol_html: str
    savol_rasm_url: str | None = None
    savol_rasm_style: str = "medium"
    jadval_html: str | None = None
    variant_a_html: str
    variant_b_html: str
    variant_c_html: str
    variant_d_html: str
    togri_javob: str
    ball: float = 1.1


class BankItemBulkIn(BaseModel):
    items: list[BankItemIn] = Field(..., min_length=1, max_length=200)


class BankItemUpdateIn(BaseModel):
    fan_id: str | None = None
    kitob_nomi: str | None = None
    bolim_nomi: str | None = None
    savol_html: str | None = None
    savol_rasm_url: str | None = None
    savol_rasm_style: str | None = None
    jadval_html: str | None = None
    variant_a_html: str | None = None
    variant_b_html: str | None = None
    variant_c_html: str | None = None
    variant_d_html: str | None = None
    togri_javob: str | None = None
    ball: float | None = None


class BankItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fan_id: str
    fan: FanOut
    kitob_nomi: str | None
    bolim_nomi: str | None
    savol_html: str
    savol_rasm_url: str | None
    savol_rasm_style: str
    jadval_html: str | None
    variant_a_html: str
    variant_b_html: str
    variant_c_html: str
    variant_d_html: str
    togri_javob: str
    ball: float
    times_shown: int
    times_correct: int
    difficulty_percent: float | None
    created_at: datetime


class BankSearchOut(BaseModel):
    items: list[BankItemOut]
    total: int


class BankSourcesOut(BaseModel):
    fanlar: list[FanOut]
    kitoblar: list[str]
    bolimlar: list[str]


class ToplamIn(BaseModel):
    name: str
    # MUHIM: to'plam ko'pi bilan 90 ta savoldan iborat bo'lishi kerak
    # (baza darajasida ham CheckConstraint bilan qo'shimcha himoyalangan --
    # app/models.py'dagi Toplam'ga qarang).
    savollar_soni: int = Field(..., ge=1, le=90)


class ToplamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    savollar_soni: int
    qiyinchilik_maqsadi_json: dict | None
    created_at: datetime


class ToplamQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    bank_item_id: str
    tartib: int
    ball: float
    bank_item: BankItemOut


class ToplamDetailOut(ToplamOut):
    questions: list[ToplamQuestionOut] = []


class AddQuestionToToplamIn(BaseModel):
    bank_item_id: str
    tartib: int
    ball: float | None = None


class ReorderToplamIn(BaseModel):
    tartib_map: dict[str, int]  # {bank_item_id: yangi_tartib}


class UpdateToplamBallIn(BaseModel):
    ball: float


class AutoFillIn(BaseModel):
    fan_id: str
    qiyinchilik_maqsadi: dict[str, float]  # {"oson": 30, "ortacha": 50, "qiyin": 20}


class AutoFillOut(BaseModel):
    added_count: int
    shortfall: dict[str, int]
    used_unrated_fallback: int


class CreateToplamExamIn(BaseModel):
    group_id: str
    name: str | None = None