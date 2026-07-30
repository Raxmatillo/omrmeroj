# -*- coding: utf-8 -*-
from typing import List
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

    # Natija PDF QR kodiga qo'yiladigan signed havolaning to'liq domeni
    # (masalan "https://api.your-domain.com"). Bo'sh bo'lsa, havola
    # nisbiy yo'l sifatida qoladi (dev/lokal test uchun yetarli, lekin
    # QR haqiqiy telefon kamerasi bilan ochilishi uchun productionda
    # to'liq domen kerak).
    PUBLIC_BASE_URL: str = ""

    # --- Telegram bot orqali login (telefon + bir martalik kod) ---
    # Botni @BotFather'dan olingan token. Bo'sh bo'lsa /auth/request-code
    # va bot process ishlamaydi.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_API_BASE: str = "https://api.telegram.org"

    VERIFICATION_CODE_LENGTH: int = 6
    VERIFICATION_CODE_TTL_MINUTES: int = 5
    VERIFICATION_CODE_MAX_ATTEMPTS: int = 5
    VERIFICATION_CODE_RESEND_COOLDOWN_SECONDS: int = 60

    # Telefon validatsiyasi
    PHONE_PATTERN: str = r"^\+998[0-9]{9}$"
    PHONE_COUNTRY_CODE: str = "998"
    PHONE_MIN_LENGTH: int = 9  # Operator kodisiz raqam uzunligi
    PHONE_MAX_LENGTH: int = 9
    PHONE_ALLOWED_OPERATORS: str = "90,91,93,94,95,97,98,99,33,88,77,55,50"

    @property
    def phone_operators_list(self) -> List[str]:
        """Operator kodlarini listga o'giradi"""
        return [op.strip() for op in self.PHONE_ALLOWED_OPERATORS.split(",")]

    # FAQAT bittasini ishlating: SettingsConfigDict (yangicha usul)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True  # O'zgaruvchilar nomi katta-kichik harfga sezgir
    )


settings = Settings()