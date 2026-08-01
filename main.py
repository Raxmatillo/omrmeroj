# main.py
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
import uvicorn

from app.config import settings
from app.database import engine
from app import models
from app.routers import auth, groups, tests, exams, results, uploads
from bot.handlers import start, contact, omr

# Bot
bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
dp.include_routers(start.router, contact.router, omr.router)

# FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(dp.start_polling(bot))
    print("✅ Bot ishga tushdi")
    yield
    task.cancel()
    await bot.session.close()

app = FastAPI(title="OMR Meroj API", lifespan=lifespan)

# Routerlar
app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(tests.router)
app.include_router(exams.router)
app.include_router(results.router)
app.include_router(uploads.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)