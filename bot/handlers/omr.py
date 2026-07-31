# -*- coding: utf-8 -*-
import logging
import re

import cv2
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, FSInputFile, Message,
    InlineKeyboardButton, InlineKeyboardMarkup,
)

from app import models
from app.config import settings
from app.database import SessionLocal
from app.services.omr_service import (
    OmrError,
    analyze_answer_sheet,
    compute_scores,
    recompute_scores_with_corrections,
    save_result,
)
from pathlib import Path

logger = logging.getLogger("omrmeroj.bot.omr")
router = Router(name="omr")


class ManualCorrectionStates(StatesGroup):
    waiting_correction = State()


async def _get_user_by_telegram_id(db, telegram_id: str) -> models.User | None:
    return db.query(models.User).filter(models.User.telegram_id == telegram_id).first()


def _save_temp_scan(warped_image, exam_student_id: str) -> str:
    out_dir = Path(settings.OUTPUT_DIR) / "pending_scans"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{exam_student_id}.jpg"
    cv2.imwrite(str(path), warped_image, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return str(path)


def _format_preview(scores: dict, student_name: str, is_owner: bool) -> str:
    subject_lines = [
        f"  \u2022 {fan}: {s['correct']}/{s['total']}"
        for fan, s in (scores.get("per_subject") or {}).items()
    ]
    subjects_text = "\n".join(subject_lines)

    header = "Natija (hali saqlanmagan):" if is_owner else "Sizning natijangiz:"
    text = (
        f"{header}\n\n"
        f"O'quvchi: {student_name}\n"
        f"To'g'ri: {scores['correct']} | Noto'g'ri: {scores['incorrect']} | "
        f"Bo'sh: {scores['blank']} | Noaniq: {scores['ambiguous']}\n"
        f"Umumiy ball: {scores['total_score']}\n\n"
        f"Fanlar bo'yicha:\n{subjects_text}"
    )
    if scores.get("variant_mismatch"):
        text += (
            "\n\n\u26A0\uFE0F TEST VARIANTI mos kelmadi -- bu boshqa talabaning "
            "javob varag'i bo'lishi mumkin, tekshiring."
        )
    return text


async def _offer_save(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\U0001F4BE Bazaga saqlash", callback_data="omr_save"),
        InlineKeyboardButton(text="\U0001F5D1 Bekor qilish", callback_data="omr_discard"),
    ]])
    await message.answer("Natijadan qoniqsangiz, saqlang:", reply_markup=kb)


@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    await state.clear()
    doc = message.document
    if doc.mime_type != "application/pdf":
        await message.answer("Iltimos, faqat PDF formatidagi javob varag'ini yuboring.")
        return
    await _process_answer_sheet(message, state, file_id=doc.file_id, filename_hint=doc.file_name or "sheet.pdf")


@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    await state.clear()
    photo = message.photo[-1]
    await _process_answer_sheet(message, state, file_id=photo.file_id, filename_hint="sheet.jpg")


async def _process_answer_sheet(message: Message, state: FSMContext, file_id: str, filename_hint: str):
    db = SessionLocal()
    try:
        status_msg = await message.answer("Qabul qilindi, tekshirilmoqda...")
        file = await message.bot.get_file(file_id)
        buffer = await message.bot.download_file(file.file_path)
        file_bytes = buffer.read()

        try:
            analysis = analyze_answer_sheet(file_bytes, filename_hint)
            scores = compute_scores(db, analysis["booklet_id"], analysis["report"])
        except OmrError as e:
            await status_msg.edit_text(f"Xatolik: {e}")
            return

        exam_student = db.get(models.ExamStudent, scores["exam_student_id"])
        exam = exam_student.exam
        student_name = exam_student.student.full_name

        requester = await _get_user_by_telegram_id(db, str(message.from_user.id))
        is_owner = requester is not None and requester.id == exam.teacher_id

        # === KIRISH NAZORATI ===
        if not is_owner and not exam.public_checking:
            await status_msg.edit_text(
                "\U0001F512 Bu imtihon uchun ommaviy tekshirish o'qituvchi tomonidan yopilgan.\n"
                "Natijangizni faqat o'qituvchingizdan bilib olishingiz mumkin."
            )
            return

        preview_path = _save_temp_scan(analysis["report"]["warped_image"], exam_student.id)
        await status_msg.edit_text(_format_preview(scores, student_name, is_owner))

        if not is_owner:
            note = (
                "\n\n\u2139\uFE0F Bu -- faqat sizga ko'rsatiladigan tekshiruv, "
                "rasmiy natijalar jadvaliga yozilmaydi."
            )
            if scores["ambiguous"] > 0:
                note += (
                    "\n\u26A0\uFE0F Ba'zi javoblar noaniq -- rasmiy (aniq) natijani "
                    "faqat o'qituvchingiz tasdiqlab, saqlashi mumkin."
                )
            await message.answer(note)
            return

        # === faqat egasi uchun: pending holatga saqlaymiz ===
        await state.update_data(
            pending_exam_student_id=exam_student.id,
            pending_scores=scores,
            pending_preview_path=preview_path,
            pending_student_name=student_name,
        )

        if scores["ambiguous"] > 0:
            ambiguous_qs = sorted(
                int(k) for k, v in scores["raw_answers"].items() if v == "MULTI"
            )
            await state.update_data(ambiguous_questions=ambiguous_qs)
            qs_str = ", ".join(str(q) for q in ambiguous_qs)
            await message.answer(
                f"\u26A0\uFE0F Quyidagi savollar noaniq: {qs_str}\n\n"
                "Iltimos to'g'ri javoblarni shu formatda yuboring (savol raqami "
                "+ harf, bo'sh joy bilan ajratib):\n\n"
                "<b>15a 24b</b>\n\n"
                "Agar talaba hech qanday variant belgilamagan bo'lsa, harf o'rniga "
                "<b>x</b> yozing (masalan: 24x). Barcha noaniq savollarni bitta "
                "xabarda yuboring."
            )
            await state.set_state(ManualCorrectionStates.waiting_correction)
        else:
            await _offer_save(message)

    except Exception:
        logger.exception("Javob varag'ini qayta ishlashda kutilmagan xato")
        await message.answer("Kutilmagan xatolik yuz berdi, birozdan keyin qayta urinib ko'ring.")
    finally:
        db.close()


@router.message(ManualCorrectionStates.waiting_correction, F.text)
async def handle_manual_correction(message: Message, state: FSMContext):
    data = await state.get_data()
    ambiguous_qs = set(data.get("ambiguous_questions", []))
    pending_scores = data.get("pending_scores")
    exam_student_id = data.get("pending_exam_student_id")

    if not pending_scores or not exam_student_id:
        await message.answer("Bu tuzatish muddati o'tgan, qaytadan javob varag'ini yuboring.")
        await state.clear()
        return

    pairs = re.findall(r"(\d+)\s*([A-Da-dXx])", message.text or "")
    if not pairs:
        await message.answer(
            "Format tushunarsiz. Masalan: <b>15a 24b</b> (yoki bo'sh bo'lsa: 24x)"
        )
        return

    corrections: dict[str, str | None] = {}
    skipped = []
    for qnum_str, letter in pairs:
        qnum = int(qnum_str)
        if qnum not in ambiguous_qs:
            skipped.append(qnum)
            continue
        letter_up = letter.upper()
        corrections[str(qnum)] = None if letter_up == "X" else letter_up

    missing = ambiguous_qs - {int(k) for k in corrections.keys()}
    if missing:
        await message.answer(
            "Quyidagi noaniq savollar hali kiritilmadi: "
            f"{', '.join(str(q) for q in sorted(missing))}. "
            "Iltimos hammasini bitta xabarda yuboring."
        )
        return

    db = SessionLocal()
    try:
        new_scores = recompute_scores_with_corrections(db, exam_student_id, pending_scores, corrections)
    except OmrError as e:
        await message.answer(f"Xatolik: {e}")
        await state.clear()
        return
    finally:
        db.close()

    await state.update_data(pending_scores=new_scores)
    await state.set_state(None)

    note = ""
    if skipped:
        note = (
            "\n\n(E'tibor bering: quyidagi raqamlar noaniq ro'yxatida yo'q edi, "
            f"o'tkazib yuborildi: {', '.join(str(q) for q in skipped)})"
        )

    student_name = data.get("pending_student_name", "")
    await message.answer(
        "\u2705 Tuzatildi!\n\n" + _format_preview(new_scores, student_name, is_owner=True) + note
    )
    await _offer_save(message)


@router.callback_query(F.data == "omr_save")
async def confirm_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "pending_exam_student_id" not in data:
        await callback.answer("Bu natija muddati o'tgan, qayta yuboring.", show_alert=True)
        return

    db = SessionLocal()
    try:
        warped = cv2.imread(data["pending_preview_path"])
        result = save_result(db, data["pending_exam_student_id"], data["pending_scores"], warped)
        await callback.message.edit_text("\u2705 Natija bazaga saqlandi.")

        if result.result_pdf_path:
            try:
                student_name = data.get("pending_student_name", "natija")
                await callback.message.answer_document(
                    FSInputFile(result.result_pdf_path, filename=f"natija_{student_name}.pdf"),
                    caption="Natija PDF",
                )
            except Exception:  # noqa: BLE001
                logger.exception("Natija PDF'ni yuborishda xato")
    except OmrError as e:
        await callback.message.answer(f"Xatolik: {e}")
    finally:
        db.close()

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "omr_discard")
async def discard_result(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Bekor qilindi.")
    await callback.answer()