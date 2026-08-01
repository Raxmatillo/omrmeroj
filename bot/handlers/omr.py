# -*- coding: utf-8 -*-
import logging
import re
from pathlib import Path

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
        f"▫️ {fan}: {s['correct']}/{s['total']}"
        for fan, s in (scores.get("per_subject") or {}).items()
    ]
    subjects_text = "\n".join(subject_lines) if subject_lines else "▫️ Maʼlumot yoʻq"

    text = (
        f"📊 <b>Natija</b>\n\n"
        f"👤 <b>Oʻquvchi:</b> {student_name}\n"
        f"✅ <b>Toʻgʻri:</b> {scores['correct']}  |  ❌ <b>Notoʻgʻri:</b> {scores['incorrect']}\n"
        f"⬜ <b>Boʻsh:</b> {scores['blank']}  |  ❓ <b>Noaniq:</b> {scores['ambiguous']}\n"
        f"🏆 <b>Jami ball:</b> {scores['total_score']}\n\n"
        f"📚 <b>Fanlar boʻyicha:</b>\n{subjects_text}"
    )
    if scores.get("variant_mismatch"):
        text += (
            "\n\n⚠️ <b>Diqqat!</b> Test varianti mos kelmadi — "
            "bu boshqa talabaning varagʻi boʻlishi mumkin."
        )
    if not is_owner:
        text += (
            "\n\n🔍 <i>Bu natija faqat sizga koʻrsatiladi va "
            "rasmiy jadvalga yozilmaydi.</i>"
        )
    return text


async def _offer_save(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Bazaga saqlash", callback_data="omr_save")],
        [InlineKeyboardButton(text="🗑 Bekor qilish", callback_data="omr_discard")],
    ])
    await message.answer("📌 Natijani saqlaysizmi?", reply_markup=kb)


@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    await state.clear()
    doc = message.document
    if doc.mime_type != "application/pdf":
        await message.answer("❌ Iltimos, faqat <b>PDF</b> formatidagi faylni yuboring.")
        return
    await _process_answer_sheet(message, state, file_id=doc.file_id, filename_hint=doc.file_name or "sheet.pdf")


@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    await state.clear()
    photo = message.photo[-1]
    await _process_answer_sheet(message, state, file_id=photo.file_id, filename_hint="sheet.jpg")


async def _process_answer_sheet(message: Message, state: FSMContext, file_id: str, filename_hint: str):
    db = SessionLocal()
    status_msg = None
    try:
        status_msg = await message.answer("🔄 Javoblar tekshirilmoqda...")

        file = await message.bot.get_file(file_id)
        buffer = await message.bot.download_file(file.file_path)
        file_bytes = buffer.read()

        analysis = analyze_answer_sheet(file_bytes, filename_hint)
        scores = compute_scores(db, analysis["booklet_id"], analysis["report"])

        exam_student = db.get(models.ExamStudent, scores["exam_student_id"])
        exam = exam_student.exam
        student_name = exam_student.student.full_name

        requester = await _get_user_by_telegram_id(db, str(message.from_user.id))
        is_owner = requester is not None and requester.id == exam.teacher_id

        if not is_owner and not exam.public_checking:
            await status_msg.edit_text(
                "🔒 Bu imtihon uchun ommaviy tekshirish <b>oʻchirilgan</b>.\n"
                "Natijangizni faqat oʻqituvchingizdan bilib olishingiz mumkin."
            )
            return

        preview_path = _save_temp_scan(analysis["report"]["warped_image"], exam_student.id)
        await status_msg.edit_text(_format_preview(scores, student_name, is_owner))

        if not is_owner:
            if scores["ambiguous"] > 0:
                await message.answer(
                    "⚠️ Baʼzi javoblar <b>noaniq</b> — rasmiy natijani "
                    "faqat oʻqituvchingiz tasdiqlay oladi."
                )
            return

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

            # 🔥 Noaniq savollar xabarini status_msg ga o'zgartiramiz
            await status_msg.answer(
                f"❓ <b>Noaniq javoblar</b>\n\n"
                f"{len(ambiguous_qs)} ta noaniq javob aniqlandi.\n"
                f"<b>Savol raqamlari:</b> {qs_str}\n\n"
                f"📌 <b>Tuzatish formati:</b>\n"
                f"<code>15a 24b 24x</code>\n"
                f"• 15-savol → A\n"
                f"• 24-savol → B\n"
                f"• 24-savol → boʻsh\n\n"
                f"<i>Barchasini bitta xabarda yuboring.</i>"
            )

            # 📋 Tugmalar (faqat 10 tagacha)
            if len(ambiguous_qs) <= 10:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"№{q}",
                        callback_data=f"fix_{q}"
                    ) for q in ambiguous_qs]
                ])
                await message.answer(
                    "📋 Noaniq savollar roʻyxati:",
                    reply_markup=kb
                )

            await state.set_state(ManualCorrectionStates.waiting_correction)
        else:
            await _offer_save(message)

    except OmrError as e:
        if status_msg:
            await status_msg.edit_text(f"❌ Xatolik: {e}")
        else:
            await message.answer(f"❌ Xatolik: {e}")
    except Exception:
        logger.exception("Javob varag'ini qayta ishlashda xatolik")
        if status_msg:
            await status_msg.edit_text("❌ Kutilmagan xatolik. Iltimos, qayta urinib koʻring.")
        else:
            await message.answer("❌ Kutilmagan xatolik. Iltimos, qayta urinib koʻring.")
    finally:
        db.close()


@router.message(ManualCorrectionStates.waiting_correction, F.text)
async def handle_manual_correction(message: Message, state: FSMContext):
    data = await state.get_data()
    ambiguous_qs = set(data.get("ambiguous_questions", []))
    pending_scores = data.get("pending_scores")
    exam_student_id = data.get("pending_exam_student_id")

    if not pending_scores or not exam_student_id:
        await message.answer("⏳ Muddati oʻtgan. Qaytadan yuboring.")
        await state.clear()
        return

    pairs = re.findall(r"(\d+)\s*([A-Da-dXx])", message.text or "")
    if not pairs:
        await message.answer(
            "❌ Format notoʻgʻri.\n\n"
            "<code>15a 24b</code> — javob A va B\n"
            "<code>24x</code> — javob boʻsh"
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
            f"❌ Kiritilmagan: {', '.join(str(q) for q in sorted(missing))}\n"
            f"<i>Iltimos, barchasini yuboring.</i>"
        )
        return

    db = SessionLocal()
    try:
        new_scores = recompute_scores_with_corrections(db, exam_student_id, pending_scores, corrections)
    except OmrError as e:
        await message.answer(f"❌ Xatolik: {e}")
        await state.clear()
        return
    finally:
        db.close()

    await state.update_data(pending_scores=new_scores)
    await state.set_state(None)

    note = ""
    if skipped:
        note = f"\n\nℹ️ Oʻtkazib yuborilgan: {', '.join(str(q) for q in skipped)}"
    student_name = data.get("pending_student_name", "")

    # 🔥 Tuzatilgan natijani yangi xabar sifatida emas, balki status_msg o'rniga yuboramiz
    await message.answer(
        f"✅ <b>Tuzatildi!</b>\n\n{_format_preview(new_scores, student_name, is_owner=True)}{note}"
    )
    await _offer_save(message)


@router.callback_query(F.data == "omr_save")
async def confirm_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "pending_exam_student_id" not in data:
        await callback.answer("⏳ Muddati oʻtgan, qayta yuboring.", show_alert=True)
        return

    db = SessionLocal()
    try:
        warped = cv2.imread(data["pending_preview_path"])
        result = save_result(db, data["pending_exam_student_id"], data["pending_scores"], warped)

        # 🔥 Xabarni tahrirlaymiz
        await callback.message.edit_text("✅ Natija bazaga saqlandi.")

        if result.result_pdf_path:
            try:
                student_name = data.get("pending_student_name", "natija")
                await callback.message.answer_document(
                    FSInputFile(result.result_pdf_path, filename=f"natija_{student_name}.pdf"),
                    caption="📄 Natija hisoboti"
                )
            except Exception:
                logger.exception("PDF yuborishda xatolik")
    except OmrError as e:
        await callback.message.answer(f"❌ Xatolik: {e}")
    finally:
        db.close()

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "omr_discard")
async def discard_result(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    # 🔥 Xabarni tahrirlaymiz
    await callback.message.edit_text("🗑 Bekor qilindi.")
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("fix_"))
async def fix_question_callback(callback: CallbackQuery, state: FSMContext):
    qnum = int(callback.data.split("_")[-1])
    data = await state.get_data()
    ambiguous_qs = data.get("ambiguous_questions", [])

    if qnum not in ambiguous_qs:
        await callback.answer("Bu savol noaniq emas.", show_alert=True)
        return

    # 🔥 Xabarni tahrirlaymiz
    await callback.message.edit_text(
        f"📝 <b>{qnum}-savol</b>\n\n"
        f"Toʻgʻri javobni yozing:\n"
        f"• <code>{qnum}a</code> — A\n"
        f"• <code>{qnum}b</code> — B\n"
        f"• <code>{qnum}x</code> — Boʻsh\n\n"
        f"<i>Yoki barchasini birga yuboring.</i>"
    )
    await callback.answer()