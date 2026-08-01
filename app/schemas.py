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
    jadval_html: str | None = None
    variant_a_html: str
    variant_b_html: str
    variant_c_html: str
    variant_d_html: str
    togri_javob: str


class QuestionOut(QuestionIn):
    model_config = ConfigDict(from_attributes=True)
    id: str

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
    test_set_id: str
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