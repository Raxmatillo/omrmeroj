# -*- coding: utf-8 -*-
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Lokal ishlaganda SQLite, productionda Supabase Postgres connection
    # string shu yerga qo'yiladi -- kodning boshqa hech qanday joyi
    # o'zgarmaydi, chunki hamma joyda faqat shu settings.DATABASE_URL orqali ishlaymiz.
    DATABASE_URL: str = "sqlite:///./omrmeroj.db"

    SECRET_KEY: str = "dev-secret-CHANGE-ME"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 15
    ALGORITHM: str = "HS256"

    # Supabase Storage (rasm yuklash uchun) -- hozircha bo'sh bo'lsa,
    # rasm yuklash endpoint lokal papkaga saqlaydi (dev fallback)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_BUCKET: str = "question-images"

    # Faqat lokal test uchun: Telegram bot tayyor bo'lmagunicha
    # teacherni to'g'ridan-to'g'ri ro'yxatdan o'tkazish imkonini beradi.
    # Productionda albatta False qilinadi.
    DEV_MODE: bool = True

    OUTPUT_DIR: str = "./generated_files"
    UPLOAD_DIR: str = "./uploads"

    # --- Telegram bot orqali login (telefon + bir martalik kod) ---
    # Botni @BotFather'dan olingan token. Bo'sh bo'lsa /auth/request-code
    # va bot process ishlamaydi.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_API_BASE: str = "https://api.telegram.org"

    VERIFICATION_CODE_LENGTH: int = 6
    VERIFICATION_CODE_TTL_MINUTES: int = 5
    VERIFICATION_CODE_MAX_ATTEMPTS: int = 5
    VERIFICATION_CODE_RESEND_COOLDOWN_SECONDS: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
