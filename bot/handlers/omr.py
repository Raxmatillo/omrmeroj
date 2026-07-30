# -*- coding: utf-8 -*-
import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message

from app import models
from app.database import SessionLocal
from app.services.omr_service import OmrError, check_answer_sheet, apply_manual_corrections

logger = logging.getLogger("omrmeroj.bot.omr")
router = Router(name="omr")


class ManualCorrectionStates(StatesGroup):
    waiting_correction = State()


async def _get_user_by_telegram_id(db, telegram_id: str) -> models.User | None:
    return db.query(models.User).filter(models.User.telegram_id == telegram_id).first()


@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    await state.clear()  # yangi fayl kelsa, eski "tuzatish kutilmoqda" holati bekor qilinadi
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
        user = await _get_user_by_telegram_id(db, str(message.from_user.id))
        if not user:
            await message.answer("Avval /start orqali ro'yxatdan o'ting.")
            return

        status_msg = await message.answer("Qabul qilindi, tekshirilmoqda...")

        file = await message.bot.get_file(file_id)
        buffer = await message.bot.download_file(file.file_path)
        file_bytes = buffer.read()

        try:
            result = check_answer_sheet(db, file_bytes, filename_hint=filename_hint)
        except OmrError as e:
            await status_msg.edit_text(f"Xatolik: {e}")
            return

        if result.exam_student.exam.teacher_id != user.id:
            await status_msg.edit_text(
                "Bu javob varag'i sizning imtihoningizga tegishli emas."
            )
            return

        await _send_result_message(status_msg, message, result)

        # YANGI: noaniq javoblar bo'lsa, qo'lda tuzatishni so'raymiz
        ambiguous_qs = sorted(
            int(k) for k, v in (result.raw_answers_json or {}).items() if v == "MULTI"
        )
        if ambiguous_qs:
            qs_str = ", ".join(str(q) for q in ambiguous_qs)
            await message.answer(
                f"⚠️ Quyidagi savollar noaniq: {qs_str}\n\n"
                "Iltimos to'g'ri javoblarni shu formatda yuboring (savol raqami "
                "+ harf, bo'sh joy bilan ajratib):\n\n"
                "<b>15a 24b</b>\n\n"
                "Agar talaba hech qanday variant belgilamagan bo'lsa, harf o'rniga "
                "<b>x</b> yozing (masalan: 24x). Barcha noaniq savollarni bitta "
                "xabarda yuboring."
            )
            await state.set_state(ManualCorrectionStates.waiting_correction)
            await state.update_data(result_id=result.id, ambiguous_questions=ambiguous_qs)

    except Exception:
        logger.exception("Javob varag'ini qayta ishlashda kutilmagan xato")
        await message.answer("Kutilmagan xatolik yuz berdi, birozdan keyin qayta urinib ko'ring.")
    finally:
        db.close()


async def _send_result_message(status_msg: Message, message: Message, result: models.Result):
    exam_student = result.exam_student
    student = exam_student.student

    subject_lines = [
        f"  \u2022 {fan}: {s['correct']}/{s['total']}"
        for fan, s in (result.per_subject_json or {}).items()
    ]
    subjects_text = "\n".join(subject_lines)

    review_note = (
        "\n\u26A0\uFE0F Ba'zi javoblar noaniq -- qo'lda tekshirish tavsiya etiladi."
        if result.status == models.ResultStatus.needs_review and result.ambiguous_count > 0
        else ""
    )
    if result.variant_mismatch:
        expected = exam_student.paper_variant_number
        got = result.detected_paper_variant
        review_note += (
            f"\n\u26A0\uFE0F TEST VARIANTI mos kelmadi: kutilgan {expected}, "
            f"belgilangan {got if got else 'belgilanmagan'}. Bu boshqa talabaning "
            f"javob varag'i bo'lishi mumkin -- tekshiring."
        )

    await status_msg.edit_text(
        "Natija tayyor!\n\n"
        f"O'quvchi: {student.full_name}\n"
        f"To'g'ri: {result.correct_count} | Noto'g'ri: {result.incorrect_count} | "
        f"Bo'sh: {result.blank_count} | Noaniq: {result.ambiguous_count}\n"
        f"Umumiy ball: {result.total_score}\n\n"
        f"Fanlar bo'yicha:\n{subjects_text}"
        f"{review_note}\n\n"
        f"Natija ID: {result.id}"
    )

    if result.result_pdf_path:
        try:
            await message.answer_document(
                FSInputFile(result.result_pdf_path, filename=f"natija_{student.full_name}.pdf"),
                caption="Natija PDF",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Natija PDF'ni Telegram orqali yuborishda xato")
            await message.answer(
                "Natija saqlandi, lekin PDF faylni shu yerda yuborishda xatolik yuz berdi. "
                "Saytdan yuklab olishingiz mumkin."
            )
    else:
        await message.answer(
            "Natija saqlandi, lekin PDF fayl hali generatsiya qilinmagan "
            "(server tomonida xatolik bo'lgan bo'lishi mumkin)."
        )


@router.message(ManualCorrectionStates.waiting_correction, F.text)
async def handle_manual_correction(message: Message, state: FSMContext):
    data = await state.get_data()
    result_id = data.get("result_id")
    ambiguous_qs = set(data.get("ambiguous_questions", []))

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
        result = db.get(models.Result, result_id)
        if not result:
            await message.answer("Natija topilmadi (eskirgan bo'lishi mumkin).")
            await state.clear()
            return

        result = apply_manual_corrections(db, result, corrections)
        await state.clear()

        note = ""
        if skipped:
            note = (
                "\n\n(E'tibor bering: quyidagi raqamlar noaniq ro'yxatida yo'q edi, "
                f"o'tkazib yuborildi: {', '.join(str(q) for q in skipped)})"
            )

        subject_lines = [
            f"  \u2022 {fan}: {s['correct']}/{s['total']}"
            for fan, s in (result.per_subject_json or {}).items()
        ]
        await message.answer(
            "✅ Tuzatildi!\n\n"
            f"To'g'ri: {result.correct_count} | Noto'g'ri: {result.incorrect_count} | "
            f"Bo'sh: {result.blank_count} | Noaniq: {result.ambiguous_count}\n"
            f"Umumiy ball: {result.total_score}\n\n"
            "Fanlar bo'yicha:\n" + "\n".join(subject_lines) + note
        )

        if result.result_pdf_path:
            try:
                await message.answer_document(
                    FSInputFile(result.result_pdf_path, filename="natija_tuzatilgan.pdf"),
                    caption="Yangilangan natija PDF",
                )
            except Exception:  # noqa: BLE001
                logger.exception("Tuzatilgan natija PDF'ni yuborishda xato")
    finally:
        db.close()