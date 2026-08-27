# -*- coding: utf-8 -*-
"""
Mijozlardan bot orqali kelgan so'rovlarni (savollar tayyorlash,
tekshirish va h.k.) navbatga qo'yish va boshqarish.

Oqim:
  - Har qanday foydalanuvchi /buyurtma buyrug'i orqali so'rov qoldiradi
    (erkin matn ko'rinishida tavsif yozadi -- "90 ta savol kerak,
    fanlar: matematika, fizika, 3-avgustgacha" kabi).
  - Admin (User.role -- teacher yoki superadmin) /buyurtmalar orqali
    faol (bekor qilinmagan) so'rovlar ro'yxatini ko'radi, har biri
    ostidagi tugmalar orqali holatini o'zgartiradi:
      Kutilmoqda -> Jarayonga olish -> Tayyor / Bekor qilish
    va to'lov holatini ("To'landi deb belgilash") belgilaydi.

Bu -- TO'LIQ AVTOMATLASHTIRILGAN TIZIM EMAS. Siz (admin) hamon qo'lda
savollarni tayyorlaysiz -- bu funksiya faqat so'rovlarning Telegram
chatida tarqalib, adashib ketmasligi uchun ODDIY NAVBAT/HISOB.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from app import models
from app.database import SessionLocal

router = Router(name="orders")


class OrderStates(StatesGroup):
    waiting_description = State()


STATUS_LABELS = {
    models.ServiceRequestStatus.pending: "\U0001F550 Kutilmoqda",       # 🕐
    models.ServiceRequestStatus.in_progress: "\u2699\ufe0f Jarayonda",  # ⚙️
    models.ServiceRequestStatus.done: "\u2705 Tayyor",                  # ✅
    models.ServiceRequestStatus.cancelled: "\u274c Bekor qilingan",     # ❌
}


def _format_order_text(req: "models.ServiceRequest") -> str:
    payment = (
        "\U0001F4B0 To'langan" if req.payment_status == models.PaymentStatus.paid
        else "\u23f3 To'lanmagan"
    )
    who = req.full_name or (f"@{req.username}" if req.username else req.telegram_id)
    return (
        f"\u2116{req.id[:8]} | {STATUS_LABELS[req.status]} | {payment}\n"
        f"\U0001F464 {who}\n"
        f"\U0001F4C5 {req.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"{req.description}"
    )


def _order_keyboard(req: "models.ServiceRequest") -> InlineKeyboardMarkup | None:
    rows = []
    if req.status == models.ServiceRequestStatus.pending:
        rows.append([InlineKeyboardButton(
            text="\u2699\ufe0f Jarayonga olish", callback_data=f"order_progress_{req.id}"
        )])
    if req.status in (models.ServiceRequestStatus.pending, models.ServiceRequestStatus.in_progress):
        rows.append([
            InlineKeyboardButton(text="\u2705 Tayyor", callback_data=f"order_done_{req.id}"),
            InlineKeyboardButton(text="\u274c Bekor qilish", callback_data=f"order_cancel_{req.id}"),
        ])
    if req.payment_status == models.PaymentStatus.unpaid:
        rows.append([InlineKeyboardButton(
            text="\U0001F4B0 To'landi deb belgilash", callback_data=f"order_paid_{req.id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


# ============================================================
# MIJOZ TOMONI: so'rov qoldirish
# ============================================================

@router.message(Command("buyurtma"))
async def cmd_buyurtma(message: Message, state: FSMContext):
    await message.answer(
        "\U0001F4DD So'rovingizni yozing -- nechta savol, qaysi fanlar, "
        "qachongacha kerakligini qisqacha tasvirlab bering.\n\n"
        "Yuborish uchun shunchaki xabar yozing."
    )
    await state.set_state(OrderStates.waiting_description)


@router.message(OrderStates.waiting_description, F.text)
async def receive_order_description(message: Message, state: FSMContext):
    db = SessionLocal()
    try:
        req = models.ServiceRequest(
            telegram_id=str(message.from_user.id),
            username=message.from_user.username,
            full_name=message.from_user.full_name,
            description=message.text,
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        await message.answer(
            f"\u2705 So'rovingiz qabul qilindi (\u2116{req.id[:8]}).\n"
            f"Tez orada siz bilan bog'lanamiz."
        )
    finally:
        db.close()
    await state.clear()


# ============================================================
# ADMIN TOMONI: navbatni ko'rish va boshqarish
# ============================================================

@router.message(Command("buyurtmalar"))
async def cmd_buyurtmalar(message: Message):
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.telegram_id == str(message.from_user.id)
        ).first()
        if not user or user.role not in (models.UserRole.teacher, models.UserRole.superadmin):
            await message.answer("Bu bo'lim faqat administratorlar uchun.")
            return

        requests = (
            db.query(models.ServiceRequest)
            .filter(models.ServiceRequest.status != models.ServiceRequestStatus.cancelled)
            .order_by(models.ServiceRequest.created_at.asc())
            .all()
        )
        if not requests:
            await message.answer("\U0001F4ED Hozircha faol so'rovlar yo'q.")
            return

        for req in requests:
            await message.answer(_format_order_text(req), reply_markup=_order_keyboard(req))
    finally:
        db.close()


@router.callback_query(F.data.startswith("order_"))
async def handle_order_action(callback: CallbackQuery):
    # "order_progress_<uuid>" -> action="progress", req_id="<uuid>"
    _, action, req_id = callback.data.split("_", 2)

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(
            models.User.telegram_id == str(callback.from_user.id)
        ).first()
        if not user or user.role not in (models.UserRole.teacher, models.UserRole.superadmin):
            await callback.answer("Ruxsat yo'q.", show_alert=True)
            return

        req = db.get(models.ServiceRequest, req_id)
        if not req:
            await callback.answer("So'rov topilmadi.", show_alert=True)
            return

        if action == "progress":
            req.status = models.ServiceRequestStatus.in_progress
        elif action == "done":
            req.status = models.ServiceRequestStatus.done
        elif action == "cancel":
            req.status = models.ServiceRequestStatus.cancelled
        elif action == "paid":
            req.payment_status = models.PaymentStatus.paid

        db.commit()
        db.refresh(req)

        await callback.message.edit_text(_format_order_text(req), reply_markup=_order_keyboard(req))
        await callback.answer("Yangilandi.")
    finally:
        db.close()
