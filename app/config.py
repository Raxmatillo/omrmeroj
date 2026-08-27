# -*- coding: utf-8 -*-
from typing import List
import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# ─── USER DATA PAPKA ──────────────────────────────────────────
def get_user_data_dir() -> Path:
    """Electron app.getPath('userData') ga mos papkani qaytaradi"""
    if sys.platform == "win32":
        return Path(os.environ.get('APPDATA', '')) / "OMR Meroj"
    elif sys.platform == "darwin":
        return Path.home() / "Library/Application Support/OMR Meroj"
    else:  # Linux
        return Path.home() / ".config/OMR Meroj"

# ─── .ENV TOPISH ─────────────────────────────────────────────
def find_env_file() -> Path | None:
    """.env faylini turli joylardan qidiradi"""
    base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path.cwd()
    env_file = base / ".env"
    if env_file.exists():
        return env_file

    user_env = get_user_data_dir() / ".env"
    if user_env.exists():
        return user_env

    local_env = Path.cwd() / ".env"
    if local_env.exists():
        return local_env

    return None

# ─── .ENV YUKLASH ────────────────────────────────────────────
env_file = find_env_file()
if env_file:
    load_dotenv(env_file)

# ─── SETTINGS ────────────────────────────────────────────────
class Settings(BaseSettings):
    # ✅ Field sifatida EMAS, property sifatida ishlatiladi
    # DATABASE_URL fieldini olib tashladik

    SECRET_KEY: str = "dev-secret-CHANGE-ME"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 15
    ALGORITHM: str = "HS256"

    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_BUCKET: str = "question-images"

    CORS_ORIGINS: str = "http://localhost:5173"

    DEV_MODE: bool = True

    PUBLIC_BASE_URL: str = ""

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_API_BASE: str = "https://api.telegram.org"
    ADMIN_TELEGRAM_CHAT_ID: str = ""
    ENABLE_BOT: bool = False

    VERIFICATION_CODE_LENGTH: int = 6
    VERIFICATION_CODE_TTL_MINUTES: int = 5
    VERIFICATION_CODE_MAX_ATTEMPTS: int = 5
    VERIFICATION_CODE_RESEND_COOLDOWN_SECONDS: int = 60

    PHONE_PATTERN: str = r"^\+998[0-9]{9}$"
    PHONE_COUNTRY_CODE: str = "998"
    PHONE_MIN_LENGTH: int = 9
    PHONE_MAX_LENGTH: int = 9
    PHONE_ALLOWED_OPERATORS: str = "90,91,93,94,95,97,98,99,33,88,77,55,50"

    BACKEND_URL: str = "http://localhost:8001"
    BRAND_NAME: str = "ME'ROJ"

    INTERNAL_API_SECRET: str = "dev-internal-secret-CHANGE-ME"

    # ─── PROPERTY'LAR ────────────────────────────────────────
    @property
    def DATABASE_URL(self) -> str:
        user_data = get_user_data_dir()
        user_data.mkdir(parents=True, exist_ok=True)
        db_path = user_data / "omrmeroj.db"
        return f"sqlite:///{db_path}"

    @property
    def UPLOAD_DIR(self) -> str:
        user_data = get_user_data_dir()
        upload_dir = user_data / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        return str(upload_dir)

    @property
    def OUTPUT_DIR(self) -> str:
        user_data = get_user_data_dir()
        output_dir = user_data / "generated_files"
        output_dir.mkdir(parents=True, exist_ok=True)
        return str(output_dir)

    @property
    def CORS_ORIGINS_LIST(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def phone_operators_list(self) -> List[str]:
        return [op.strip() for op in self.PHONE_ALLOWED_OPERATORS.split(",")]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

settings = Settings()