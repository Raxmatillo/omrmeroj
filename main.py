# main.py
import asyncio
from contextlib import asynccontextmanager
import os
import shutil
import sys
from pathlib import Path

import logging
from alembic.config import Config
from alembic import command

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.config import settings
from app.database import engine
from app import models
from app.routers import auth, groups, tests, exams, results, uploads



# ─── LOGGING ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# models.Base.metadata.create_all(engine)
# logger.info("✅ Jadvallar yaratildi (agar mavjud bo'lmasa)")

# ─── BOT ─────────────────────────────────────────────────────
ENABLE_BOT = getattr(settings, 'ENABLE_BOT', False)
TELEGRAM_TOKEN = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')

logger.info(f"ENABLE_BOT: {ENABLE_BOT}, Token present: {bool(TELEGRAM_TOKEN)}")

async def run_bot():
    """Bot polling ni ishga tushiradi. Xatolik bo'lsa, log qiladi."""
    try:
        from aiogram import Bot, Dispatcher
        from bot.handlers import start, contact, omr, orders, admin
        bot = Bot(token=TELEGRAM_TOKEN)
        dp = Dispatcher()
        dp.include_routers(start.router, contact.router, omr.router, orders.router, admin.router)
        logger.info("✅ Bot ishga tushdi")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Bot xatosi: {e}")

# ─── LIFESPAN ───────────────────────────────────────────────
if ENABLE_BOT and TELEGRAM_TOKEN:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Bot ishga tushirilmoqda...")
        task = asyncio.create_task(run_bot())
        yield
        task.cancel()
        logger.info("Bot to'xtatildi")
else:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("ℹ️ Bot o'chirilgan (ENABLE_BOT=false yoki token yo'q)")
        yield

def migrate_old_database():
    """Eski bazani yangi joyga ko‘chiradi (agar mavjud bo‘lsa)"""
    from app.config import get_user_data_dir

    user_data = get_user_data_dir()
    new_db_path = user_data / "omrmeroj.db"

    # Agar yangi joyda baza mavjud bo‘lsa, hech narsa qilma
    if new_db_path.exists():
        print("[OK] Ma'lumotlar bazasi allaqachon mavjud.")
        return

    # Eski joylarni qidirish
    old_paths = [
        Path.cwd() / "omrmeroj.db",
        Path(sys._MEIPASS) / "omrmeroj.db" if getattr(sys, 'frozen', False) else None,
        Path.cwd() / "backend" / "omrmeroj.db",
        Path(os.environ.get('PROGRAMFILES', '')) / "OMR Meroj" / "resources" / "app.asar.unpacked" / "backend" / "omrmeroj.db",
        Path(os.environ.get('LOCALAPPDATA', '')) / "Programs" / "OMR Meroj" / "resources" / "app.asar.unpacked" / "backend" / "omrmeroj.db",
    ]

    for old_path in old_paths:
        if old_path and old_path.exists():
            try:
                shutil.copy2(old_path, new_db_path)
                print(f"[OK] Baza ko'chirildi: {old_path} -> {new_db_path}")
                return
            except Exception as e:
                print(f"[WARN] Bazani ko'chirishda xatolik: {e}")

    print("[INFO] Eski baza topilmadi, yangi baza yaratiladi.")

def run_migrations():
    ...
    # try:
    #     if getattr(sys, 'frozen', False):
    #         # PyInstaller orqali yig'ilgan .exe ichida ishlayapmiz
    #         base_path = sys._MEIPASS
    #     else:
    #         base_path = os.path.dirname(os.path.abspath(__file__))

    #     alembic_cfg = Config(os.path.join(base_path, "alembic.ini"))
    #     alembic_cfg.set_main_option("script_location", os.path.join(base_path, "alembic"))
    #     alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    #     command.upgrade(alembic_cfg, "head")
    #     logger.info("✅ Migratsiyalar muvaffaqiyatli qo'llandi")
    # except Exception as e:
    #     logger.error(f"❌ Migratsiya xatosi: {e}")

run_migrations()

# ─── FASTAPI ─────────────────────────────────────────────────
app = FastAPI(title="OMR Meroj API", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://meroj.uz", "https://merojs.uz", "https://omr.meroj.uz"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "Authorization", "Content-Type", "X-Requested-With", "Accept", "Origin", "Access-Control-Request-Method", "Access-Control-Request-Headers"],
)

# Routerlar
app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(tests.router)
app.include_router(exams.router)
app.include_router(results.router)
app.include_router(uploads.router)

migrate_old_database()


# Upload fayllar
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

app.mount("/uploads/files", StaticFiles(directory=settings.UPLOAD_DIR), name="uploaded-files")


# Health check
@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)