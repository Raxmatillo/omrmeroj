# -*- coding: utf-8 -*-
import logging

from aiogram import F, Router
from aiogram.types import FSInputFile, Message

from app import models
from app.database import SessionLocal
from app.services.omr_service import OmrError, check_answer_sheet

logger = logging.getLogger("omrmeroj.bot.omr")
router = Router(name="omr")


async def _get_user_by_telegram_id(db, telegram_id: str) -> models.User | None:
    return db.query(models.User).filter(models.User.telegram_id == telegram_id).first()


@router.message(F.document)
async def handle_document(message: Message):
    doc = message.document
    if doc.mime_type != "application/pdf":
        await message.answer("Iltimos, faqat PDF formatidagi javob varag'ini yuboring.")
        return
    await _process_answer_sheet(message, file_id=doc.file_id, filename_hint=doc.file_name or "sheet.pdf")


@router.message(F.photo)
async def handle_photo(message: Message):
    # Eng katta o'lchamdagi versiyasini olamiz
    photo = message.photo[-1]
    await _process_answer_sheet(message, file_id=photo.file_id, filename_hint="sheet.jpg")


async def _process_answer_sheet(message: Message, file_id: str, filename_hint: str):
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

        # MUHIM: bu javob varag'i boshqa teacherning imtihoniga tegishli
        # bo'lishi mumkin (booklet_id orqali topiladi, telegram user
        # bilan bog'liq emas) -- shuning uchun natija shu teacherning
        # o'ziga tegishli ekanligini tekshiramiz (app/routers/results.py
        # dagi /results/check endpointidagi bir xil himoya).
        if result.exam_student.exam.teacher_id != user.id:
            await status_msg.edit_text(
                "Bu javob varag'i sizning imtihoningizga tegishli emas."
            )
            return

        exam_student = result.exam_student
        student = exam_student.student

        subject_lines = [
            f"  \u2022 {fan}: {s['correct']}/{s['total']}"
            for fan, s in (result.per_subject_json or {}).items()
        ]
        subjects_text = "\n".join(subject_lines)

        review_note = (
            "\n\u26A0\uFE0F Ba'zi javoblar noaniq -- qo'lda tekshirish tavsiya etiladi."
            if result.status == models.ResultStatus.needs_review
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

        # Natija PDF tayyor bo'lsa -- botning o'zi shu yerda yuboradi,
        # saytga alohida kirib yuklab olish shart emas.
        if result.result_pdf_path:
            try:
                await message.answer_document(
                    FSInputFile(result.result_pdf_path, filename=f"natija_{student.full_name}.pdf"),
                    caption="Natija PDF",
                )
            except Exception:  # noqa: BLE001 -- fayl yuborilmasa ham, natija DB'da saqlangan
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

    except Exception:
        logger.exception("Javob varag'ini qayta ishlashda kutilmagan xato")
        await message.answer("Kutilmagan xatolik yuz berdi, birozdan keyin qayta urinib ko'ring.")
    finally:
        db.close()