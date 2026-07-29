# -*- coding: utf-8 -*-
from datetime import datetime
from pydantic import BaseModel, ConfigDict


# ---------- AUTH ----------

class DevRegisterIn(BaseModel):
    phone: str
    password: str
    full_name: str | None = None
    role: str = "teacher"


class LoginIn(BaseModel):
    phone: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    phone: str
    full_name: str | None
    role: str


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


# ---------- TESTLAR ----------

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
    togri_javob: str  # A/B/C/D


class QuestionOut(QuestionIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


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
    group_id: str
    test_set_id: str


class ExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    exam_code: str
    group_id: str
    test_set_id: str
    total_questions: int
    status: str
    created_at: datetime
    expires_at: datetime | None
