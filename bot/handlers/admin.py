# -*- coding: utf-8 -*-
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.database import SessionLocal
from app import models
from app.utils.results_export import export_teacher_results_excel

router = Router(name="admin")


@router.message(Command("natijalar"))
async def show_admin_panel(message: Message):
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.telegram_id == str(message.from_user.id)
        ).first()
        if not user or user.role not in (models.UserRole.teacher, models.UserRole.superadmin):
            await message.answer("Bu bo'lim faqat o'qituvchilar uchun.")
            return

        total_results = (
            db.query(models.Result)
            .join(models.ExamStudent).join(models.Exam)
            .filter(models.Exam.teacher_id == user.id)
            .count()
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📥 Excel yuklab olish", callback_data="admin_export_xlsx"),
        ]])
        await message.answer(
            f"📊 Sizning natijalar bazangiz: jami {total_results} ta natija.\n"
            "Excel formatida to'liq jadvalni yuklab olishingiz mumkin.",
            reply_markup=kb,
        )
    finally:
        db.close()


@router.callback_query(F.data == "admin_export_xlsx")
async def export_xlsx(callback):
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.telegram_id == str(callback.from_user.id)
        ).first()
        if not user:
            await callback.answer("Ruxsat yo'q.", show_alert=True)
            return
        buf = export_teacher_results_excel(db, user.id)
        await callback.message.answer_document(
            BufferedInputFile(buf.read(), filename="natijalar.xlsx"),
            caption="Natijalar jadvali",
        )
        await callback.answer()
    finally:
        db.close()