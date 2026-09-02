# -*- coding: utf-8 -*-
"""
SAVOLLAR BANKI ARXITEKTURASI -- 2-QISM: XIZMAT (SERVICE) QATLAMI

Bu faylda hali HECH QANDAY API ENDPOINT yo'q (3-qismda qo'shiladi) --
faqat sof Python funksiyalar, ular ustiga router yozish 3-qismda
bo'ladi. Shu tufayli bu faylni alohida sinab ko'rish (masalan bitta
skript yozib chaqirib ko'rish) mumkin, API'siz ham.

Tarkib:
  1. QuestionBankItem CRUD + qidiruv/filter
  2. Toplam CRUD (savol qo'shish/olib tashlash/tartib/ball)
  3. Avtomatik to'ldirish (qiyinchilik maqsadiga qarab)
  4. "KO'PRIK" -- Toplam'ni eski Question dict formatiga o'girish
     (randomization.py/exam_service.py'ning build_shuffled_booklet
     kutayotgan aniq shaklda -- app/services/exam_service.py dagi
     _question_to_dict() bilan bir xil kalitlar)
  5. QuestionAttempt yozish + qiyinchilik statistikasini yangilash
     (denormalizatsiya -- QuestionBankItem.times_shown/times_correct/
     difficulty_percent real vaqtda yangilanadi, lekin istalgan payt
     recompute_difficulty() bilan asl QuestionAttempt yozuvlaridan
     qayta hisoblab to'g'irlash ham mumkin)

MUHIM: bu fayl exam_service.py/randomization.py/omr_service.py'ni
O'ZGARTIRMAYDI. Ularni 3-qismda Exam.toplam_id qo'shilganda ulaymiz.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Integer, func, or_
from sqlalchemy.orm import Session

from app import models


class BankServiceError(Exception):
    """Foydalanuvchiga to'g'ridan-to'g'ri ko'rsatsa bo'ladigan xato."""


# =============================================================
# DTM qoidasi: "Majburiy fanlar" bloki (pptx slide 1 va 3) --
# tartib 1-30 oralig'ida FAQAT shu 3 fan bo'lishi mumkin, har biridan
# 10 tadan OSHMASLIGI SHART (jami 30 ta). Fan nomlari `Fan` jadvalida
# saqlangan matn bilan ANIQ mos kelishi kerak (katta-kichik harf
# farqlanadi -- agar o'qituvchi "ona tili" deb kichik harf bilan
# ro'yxatdan o'tkazgan bo'lsa, bu tekshiruv uni "Ona tili" deb
# TANIMAYDI -- shuning uchun frontend'da fan nomlarini standartlashtirib
# ko'rsatish tavsiya etiladi).
# =============================================================
MAJBURIY_FANLAR = {"Ona tili", "Matematika", "Tarix"}
MAJBURIY_FAN_LIMIT = 10
MAJBURIY_SLOT_SIZE = 30  # 1-30 oraliq -- "majburiy fanlar" bloki


def _validate_majburiy_slot(
    db: Session, toplam_id: str, bank_item: models.QuestionBankItem, tartib: int,
    *, exclude_bank_item_id: str | None = None,
) -> None:
    """
    YANGI: agar savol "majburiy fanlar" blokiga (tartib 1-30
    oralig'iga) qo'shilayotgan bo'lsa -- fan nomi FAQAT
    Ona tili/Matematika/Tarix bo'lishi, va har biridan 10 tadan
    OSHMASLIGI SHART. `exclude_bank_item_id` -- ball/tartib
    yangilanayotganda o'sha savolning o'zini sanoqqa qo'shib
    yubormaslik uchun.
    """
    if tartib > MAJBURIY_SLOT_SIZE:
        return  # bu savol majburiy blokdan tashqarida -- tekshiruv shart emas

    fan_nomi = bank_item.fan.name if bank_item.fan else ''

    if fan_nomi not in MAJBURIY_FANLAR:
        raise BankServiceError(
            f"1-{MAJBURIY_SLOT_SIZE}-tartib -- 'Majburiy fanlar' bloki. "
            f"Bu yerga faqat {', '.join(sorted(MAJBURIY_FANLAR))} fanlaridan "
            f"savol qo'shish mumkin (kiritilgan: '{bank_item.fan}')."
        )

    query = (
        db.query(models.ToplamQuestion)
        .join(models.QuestionBankItem, models.ToplamQuestion.bank_item_id == models.QuestionBankItem.id)
        .filter(
            models.ToplamQuestion.toplam_id == toplam_id,
            models.ToplamQuestion.tartib <= MAJBURIY_SLOT_SIZE,
            models.QuestionBankItem.fan_id == bank_item.fan_id,
        )
    )
    if exclude_bank_item_id:
        query = query.filter(models.ToplamQuestion.bank_item_id != exclude_bank_item_id)
    same_fan_count = query.count()

    if same_fan_count >= MAJBURIY_FAN_LIMIT:
        raise BankServiceError(
            f"'{bank_item.fan}' fanidan majburiy blokda allaqachon "
            f"{MAJBURIY_FAN_LIMIT} ta savol bor -- ko'proq qo'shib bo'lmaydi."
        )


def _validate_tartib_free(db: Session, toplam_id: str, tartib: int, *, exclude_bank_item_id: str | None = None) -> None:
    """
    YANGI: bitta to'plamda ikkita savol bir xil tartib raqamiga ega
    bo'lib qolmasligi uchun. Agar tekshirilmasa, javob varag'ida
    ikkita savol bitta bubble-qatorga to'qnashib, PDF generatsiya
    paytida noto'g'ri/kutilmagan natijaga olib kelishi mumkin.
    """
    query = db.query(models.ToplamQuestion).filter(
        models.ToplamQuestion.toplam_id == toplam_id,
        models.ToplamQuestion.tartib == tartib,
    )
    if exclude_bank_item_id:
        query = query.filter(models.ToplamQuestion.bank_item_id != exclude_bank_item_id)
    if query.first() is not None:
        raise BankServiceError(f"Tartib #{tartib} allaqachon band -- avval o'sha savolni olib tashlang yoki boshqa tartib tanlang.")


# =============================================================
# 0. Fan (Subject) -- CRUD
#
# O'qituvchi savol qo'shishdan OLDIN fanni bir marta ro'yxatdan
# o'tkazadi, keyin har bir savolda shundan TANLAYDI (erkin matn
# kiritmaydi). Bu -- yozuv xilma-xilligidan (masalan bir xil fan
# turlicha yozilib, statistika bo'linib ketishidan) himoya qiladi.
# =============================================================

def create_fan(db: Session, *, teacher_id: str, name: str) -> models.Fan:
    name = name.strip()
    if not name:
        raise BankServiceError("Fan nomi bo'sh bo'lishi mumkin emas")

    already = (
        db.query(models.Fan)
        .filter(models.Fan.teacher_id == teacher_id, models.Fan.name == name)
        .first()
    )
    if already is not None:
        raise BankServiceError(f"'{name}' fani allaqachon ro'yxatdan o'tgan")

    fan = models.Fan(teacher_id=teacher_id, name=name)
    db.add(fan)
    db.commit()
    db.refresh(fan)
    return fan


def get_fan(db: Session, fan_id: str, *, teacher_id: str) -> models.Fan:
    fan = (
        db.query(models.Fan)
        .filter(models.Fan.id == fan_id, models.Fan.teacher_id == teacher_id)
        .first()
    )
    if fan is None:
        raise BankServiceError("Fan topilmadi")
    return fan


def list_fans(db: Session, *, teacher_id: str) -> list[models.Fan]:
    return (
        db.query(models.Fan)
        .filter(models.Fan.teacher_id == teacher_id)
        .order_by(models.Fan.name)
        .all()
    )


def update_fan(db: Session, fan_id: str, *, teacher_id: str, name: str) -> models.Fan:
    fan = get_fan(db, fan_id, teacher_id=teacher_id)
    name = name.strip()
    if not name:
        raise BankServiceError("Fan nomi bo'sh bo'lishi mumkin emas")

    already = (
        db.query(models.Fan)
        .filter(models.Fan.teacher_id == teacher_id, models.Fan.name == name, models.Fan.id != fan_id)
        .first()
    )
    if already is not None:
        raise BankServiceError(f"'{name}' fani allaqachon ro'yxatdan o'tgan")

    fan.name = name
    db.commit()
    db.refresh(fan)
    return fan


def delete_fan(db: Session, fan_id: str, *, teacher_id: str) -> None:
    """Agar bu fanda hali savollar bo'lsa -- o'CHIRILMAYDI (xato
    qaytariladi). Sabab: fan_id NOT NULL, shuning uchun "osilib
    qolgan" savol paydo bo'lmasligi kerak -- o'qituvchi avval o'sha
    savollarni boshqa fanga ko'chirishi yoki o'chirishi kerak."""
    fan = get_fan(db, fan_id, teacher_id=teacher_id)

    in_use = (
        db.query(models.QuestionBankItem)
        .filter(models.QuestionBankItem.fan_id == fan_id)
        .count()
    )
    if in_use > 0:
        raise BankServiceError(
            f"Bu fanda {in_use} ta savol bor -- avval ularni boshqa fanga o'tkazing yoki o'chiring"
        )

    db.delete(fan)
    db.commit()


# =============================================================
# 1. QuestionBankItem -- CRUD
# =============================================================

def create_bank_item(
    db: Session,
    *,
    teacher_id: str,
    fan_id: str,
    savol_html: str,
    variant_a_html: str,
    variant_b_html: str,
    variant_c_html: str,
    variant_d_html: str,
    togri_javob: str,
    kitob_nomi: str | None = None,
    bolim_nomi: str | None = None,
    savol_rasm_url: str | None = None,
    savol_rasm_style: str = "medium",
    jadval_html: str | None = None,
    ball: float = 1.1,
) -> models.QuestionBankItem:
    letter = togri_javob.strip().upper()
    if letter not in ("A", "B", "C", "D"):
        raise BankServiceError(f"togri_javob noto'g'ri: {togri_javob!r} (A/B/C/D bo'lishi kerak)")

    get_fan(db, fan_id, teacher_id=teacher_id)  # mavjudligi/egaligini tekshiradi

    item = models.QuestionBankItem(
        teacher_id=teacher_id,
        fan_id=fan_id,
        kitob_nomi=(kitob_nomi or "").strip() or None,
        bolim_nomi=(bolim_nomi or "").strip() or None,
        savol_html=savol_html,
        savol_rasm_url=savol_rasm_url,
        savol_rasm_style=savol_rasm_style,
        jadval_html=jadval_html,
        variant_a_html=variant_a_html,
        variant_b_html=variant_b_html,
        variant_c_html=variant_c_html,
        variant_d_html=variant_d_html,
        togri_javob=letter,
        ball=ball,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def create_bank_items_bulk(
    db: Session, *, teacher_id: str, items: list[dict],
) -> list[models.QuestionBankItem]:
    """create_bank_item()ning KO'PLAB yozuv uchun varianti -- kitobdan
    ketma-ket bir nechta savolni bir vaqtda kiritish uchun (bitta
    HTTP so'rov, bitta commit). `items` -- create_bank_item() bilan
    bir xil kalitlarga ega dict'lar ro'yxati (`teacher_id`siz).

    MUHIM: agar RO'YXATDAGI BIRORTA savolda xato (masalan yaroqsiz
    togri_javob yoki mavjud bo'lmagan fan_id) bo'lsa -- HECH BIRI
    saqlanmaydi (butun ro'yxat bitta "hammasi yoki hech biri"
    amaliyot sifatida ishlaydi, yarim-yozilgan holatning oldini
    olish uchun)."""
    if not items:
        raise BankServiceError("Bo'sh ro'yxat -- hech qanday savol berilmagan")

    # Fan egaligini oldindan (bir marta har bir noyob fan_id uchun)
    # tekshiramiz -- N marta emas.
    fan_ids = {row["fan_id"] for row in items if row.get("fan_id")}
    for fan_id in fan_ids:
        get_fan(db, fan_id, teacher_id=teacher_id)

    created: list[models.QuestionBankItem] = []
    for idx, row in enumerate(items):
        togri_javob = row.get("togri_javob", "")
        letter = togri_javob.strip().upper()
        if letter not in ("A", "B", "C", "D"):
            raise BankServiceError(
                f"{idx + 1}-savolda togri_javob noto'g'ri: {togri_javob!r} (A/B/C/D bo'lishi kerak)"
            )

        item = models.QuestionBankItem(
            teacher_id=teacher_id,
            fan_id=row["fan_id"],
            kitob_nomi=(row.get("kitob_nomi") or "").strip() or None,
            bolim_nomi=(row.get("bolim_nomi") or "").strip() or None,
            savol_html=row["savol_html"],
            savol_rasm_url=row.get("savol_rasm_url"),
            savol_rasm_style=row.get("savol_rasm_style", "medium"),
            jadval_html=row.get("jadval_html"),
            variant_a_html=row["variant_a_html"],
            variant_b_html=row["variant_b_html"],
            variant_c_html=row["variant_c_html"],
            variant_d_html=row["variant_d_html"],
            togri_javob=letter,
            ball=row.get("ball", 1.1),
        )
        db.add(item)
        created.append(item)

    db.commit()
    for item in created:
        db.refresh(item)
    return created


def get_bank_item(db: Session, item_id: str, *, teacher_id: str) -> models.QuestionBankItem:
    item = (
        db.query(models.QuestionBankItem)
        .filter(
            models.QuestionBankItem.id == item_id,
            models.QuestionBankItem.teacher_id == teacher_id,
        )
        .first()
    )
    if item is None:
        raise BankServiceError("Savol topilmadi")
    return item


_UPDATABLE_FIELDS = (
    "fan_id", "kitob_nomi", "bolim_nomi", "savol_html", "savol_rasm_url",
    "savol_rasm_style", "jadval_html", "variant_a_html", "variant_b_html",
    "variant_c_html", "variant_d_html", "togri_javob", "ball",
)


def update_bank_item(db: Session, item_id: str, *, teacher_id: str, **fields) -> models.QuestionBankItem:
    """Faqat berilgan (None bo'lmagan) maydonlarni yangilaydi -- qisman
    (partial) update. Masalan faqat `ball`ni o'zgartirish uchun
    `update_bank_item(db, id, teacher_id=t, ball=2.2)` yetarli."""
    item = get_bank_item(db, item_id, teacher_id=teacher_id)

    unknown = set(fields) - set(_UPDATABLE_FIELDS)
    if unknown:
        raise BankServiceError(f"Noma'lum maydon(lar): {', '.join(sorted(unknown))}")

    if "togri_javob" in fields and fields["togri_javob"] is not None:
        letter = fields["togri_javob"].strip().upper()
        if letter not in ("A", "B", "C", "D"):
            raise BankServiceError(f"togri_javob noto'g'ri: {fields['togri_javob']!r}")
        fields["togri_javob"] = letter

    if "fan_id" in fields and fields["fan_id"] is not None:
        get_fan(db, fields["fan_id"], teacher_id=teacher_id)  # mavjudligi/egaligini tekshiradi

    for key in ("kitob_nomi", "bolim_nomi"):
        if key in fields and fields[key] is not None:
            fields[key] = fields[key].strip() or None

    for key, value in fields.items():
        if value is not None:
            setattr(item, key, value)

    db.commit()
    db.refresh(item)
    return item


def delete_bank_item(db: Session, item_id: str, *, teacher_id: str) -> None:
    """DIQQAT: agar bu savol biror Toplam'da ishlatilayotgan bo'lsa,
    ToplamQuestion'dagi bog'lanish ham (ON CASCADE emas, qo'lda) birga
    o'chiriladi -- aks holda "osilib qolgan" (orphan) bog'lanish
    qoladi. QuestionAttempt tarixi esa ATAYLAB saqlanib qoladi (o'sha
    savol o'tmishda qanday natija bergani -- tarixiy ma'lumot, savol
    o'chirilgani bilan yo'qolmasligi kerak)."""
    item = get_bank_item(db, item_id, teacher_id=teacher_id)

    db.query(models.ToplamQuestion).filter(
        models.ToplamQuestion.bank_item_id == item_id
    ).delete(synchronize_session=False)

    db.delete(item)
    db.commit()


# --- Qidiruv/filter ---

@dataclass
class BankSearchResult:
    items: list[models.QuestionBankItem]
    total: int


def search_bank_items(
    db: Session,
    *,
    teacher_id: str,
    fan_id: str | None = None,
    kitob_nomi: str | None = None,
    bolim_nomi: str | None = None,
    search_text: str | None = None,
    difficulty_min: float | None = None,
    difficulty_max: float | None = None,
    daraja: str | None = None,
    only_unrated: bool = False,
    times_shown_min: int | None = None,  # ✅ QO'SHILDI
    times_shown_max: int | None = None,  # ✅ QO'SHILDI
    limit: int = 50,
    offset: int = 0,
) -> BankSearchResult:
    """
    - fan_id/kitob_nomi/bolim_nomi -- aniq mos kelish (exact match).
    - search_text -- savol matni ichidan erkin qidiruv (LIKE, katta-
      kichik harflarga sezgir emas).
    - difficulty_min/max -- QuestionBankItem.difficulty_percent oralig'i
      (masalan faqat "qiyin" savollarni ko'rish uchun difficulty_max=40).
    - daraja -- QULAYLIK UCHUN: "oson"/"ortacha"/"qiyin" (auto_fill_toplam
      bilan bir xil segmentlar, pastdagi _DIFFICULTY_BANDS'ga qarang).
      Berilsa, difficulty_min/max E'TIBORGA OLINMAYDI (daraja ustunlik
      qiladi) -- ikkalasini bir vaqtda ishlatish shart emas, lekin
      chalkashlik bo'lmasligi uchun aniq ustunlik tartibi belgilangan.
    - only_unrated=True -- faqat hali baholanmagan (difficulty_percent
      IS NULL) savollarni qaytaradi; yuqoridagilar bilan birga
      ishlatilmaydi (ular bo'lsa e'tiborga olinmaydi).
    """
    q = db.query(models.QuestionBankItem).filter(
        models.QuestionBankItem.teacher_id == teacher_id
    )

    if fan_id:
        q = q.filter(models.QuestionBankItem.fan_id == fan_id)
    if kitob_nomi:
        q = q.filter(models.QuestionBankItem.kitob_nomi == kitob_nomi)
    if bolim_nomi:
        q = q.filter(models.QuestionBankItem.bolim_nomi == bolim_nomi)
    if search_text:
        like = f"%{search_text.strip()}%"
        q = q.filter(
            or_(
                models.QuestionBankItem.savol_html.ilike(like),
                models.QuestionBankItem.variant_a_html.ilike(like),
                models.QuestionBankItem.variant_b_html.ilike(like),
                models.QuestionBankItem.variant_c_html.ilike(like),
                models.QuestionBankItem.variant_d_html.ilike(like),
            )
        )

    if only_unrated:
        q = q.filter(models.QuestionBankItem.difficulty_percent.is_(None))
    elif daraja:
        if daraja not in _DIFFICULTY_BANDS:
            raise BankServiceError(
                f"daraja noto'g'ri: {daraja!r} (kutilgan: {', '.join(_DIFFICULTY_BANDS)})"
            )
        lo, hi = _DIFFICULTY_BANDS[daraja]
        q = q.filter(
            models.QuestionBankItem.difficulty_percent.isnot(None),
            models.QuestionBankItem.difficulty_percent >= lo,
        )
        q = (
            q.filter(models.QuestionBankItem.difficulty_percent <= hi)
            if daraja == "oson"
            else q.filter(models.QuestionBankItem.difficulty_percent < hi)
        )
    else:
        if difficulty_min is not None:
            q = q.filter(models.QuestionBankItem.difficulty_percent >= difficulty_min)
        if difficulty_max is not None:
            q = q.filter(models.QuestionBankItem.difficulty_percent <= difficulty_max)

    if times_shown_min is not None:
        q = q.filter(models.QuestionBankItem.times_shown >= times_shown_min)
    if times_shown_max is not None:
        q = q.filter(models.QuestionBankItem.times_shown <= times_shown_max)
    total = q.count()
    items = (
        q.order_by(models.QuestionBankItem.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return BankSearchResult(items=items, total=total)


def list_distinct_sources(db: Session, *, teacher_id: str, fan_id: str | None = None) -> dict:
    """Frontend'dagi filter/datalist'larni to'ldirish uchun."""
    fanlar = list_fans(db, teacher_id=teacher_id)

    base = db.query(models.QuestionBankItem).filter(
        models.QuestionBankItem.teacher_id == teacher_id
    )
    # ✅ YANGI QO'SHILDI:
    if fan_id:
        base = base.filter(models.QuestionBankItem.fan_id == fan_id)

    kitoblar = [
        r[0] for r in base.with_entities(models.QuestionBankItem.kitob_nomi).distinct().all() if r[0]
    ]
    bolimlar = [
        r[0] for r in base.with_entities(models.QuestionBankItem.bolim_nomi).distinct().all() if r[0]
    ]
    return {
        "fanlar": fanlar,
        "kitoblar": sorted(kitoblar),
        "bolimlar": sorted(bolimlar),
    }


# =============================================================
# 2. Toplam -- CRUD
# =============================================================

def create_toplam(
    db: Session, *, teacher_id: str, name: str, savollar_soni: int,
    qiyinchilik_maqsadi: dict | None = None,
) -> models.Toplam:
    # Baza darajasidagi CheckConstraint (ck_toplam_savollar_soni_max90)
    # bilan bir xil qoida -- shu yerda oldindan tekshirib, foydalanuvchiga
    # tushunarli xato xabarini beramiz (baza xatosi o'rniga).
    if not (0 < savollar_soni <= 90):
        raise BankServiceError("To'plamdagi savollar soni 1 dan 90 gacha bo'lishi kerak")

    toplam = models.Toplam(
        teacher_id=teacher_id,
        name=name.strip(),
        savollar_soni=savollar_soni,
        qiyinchilik_maqsadi_json=qiyinchilik_maqsadi,
    )
    db.add(toplam)
    db.commit()
    db.refresh(toplam)
    return toplam


def get_toplam(db: Session, toplam_id: str, *, teacher_id: str) -> models.Toplam:
    toplam = (
        db.query(models.Toplam)
        .filter(models.Toplam.id == toplam_id, models.Toplam.teacher_id == teacher_id)
        .first()
    )
    if toplam is None:
        raise BankServiceError("To'plam topilmadi")
    return toplam


def list_toplamlar(db: Session, *, teacher_id: str) -> list[models.Toplam]:
    return (
        db.query(models.Toplam)
        .filter(models.Toplam.teacher_id == teacher_id)
        .order_by(models.Toplam.created_at.desc())
        .all()
    )


def delete_toplam(db: Session, toplam_id: str, *, teacher_id: str) -> None:
    """MUHIM: bu faqat Toplam+ToplamQuestion'larni o'chiradi.
    QuestionBankItem'larning o'zi (mustaqil bo'lgani uchun) SAQLANIB
    QOLADI -- ular boshqa to'plamlarda ham ishlatilayotgan bo'lishi
    mumkin. `cascade="all, delete-orphan"` Toplam.items orqali
    ToplamQuestion yozuvlarini avtomatik tozalaydi."""
    toplam = get_toplam(db, toplam_id, teacher_id=teacher_id)
    db.delete(toplam)
    db.commit()


def add_question_to_toplam(
    db: Session, toplam_id: str, bank_item_id: str, *, teacher_id: str,
    tartib: int, ball: float | None = None, skip_majburiy_check: bool = False,
) -> models.ToplamQuestion:
    """`ball` berilmasa, bank_item'ning standart ballidan olinadi
    (lekin shu to'plam uchun MUSTAQIL nusxa sifatida saqlanadi --
    keyin bank_item.ball o'zgarsa ham, bu to'plamdagi ball o'zgarmay
    qoladi, chunki ToplamQuestion.ball ustuni alohida).

    `skip_majburiy_check=True` -- agar to'plam DTM formatida bo'lmasa
    (masalan "majburiy fanlar" tushunchasi ishlatilmaydigan boshqa
    turdagi test) qo'lda o'chirib qo'yish mumkin."""
    toplam = get_toplam(db, toplam_id, teacher_id=teacher_id)
    item = get_bank_item(db, bank_item_id, teacher_id=teacher_id)

    already = (
        db.query(models.ToplamQuestion)
        .filter(
            models.ToplamQuestion.toplam_id == toplam_id,
            models.ToplamQuestion.bank_item_id == bank_item_id,
        )
        .first()
    )
    if already is not None:
        raise BankServiceError("Bu savol allaqachon shu to'plamda bor")

    # YANGI: tartib to'qnashuvi va "majburiy fanlar" qoidasi tekshiruvi
    _validate_tartib_free(db, toplam_id, tartib)
    if not skip_majburiy_check:
        _validate_majburiy_slot(db, toplam_id, item, tartib)

    link = models.ToplamQuestion(
        toplam_id=toplam.id,
        bank_item_id=item.id,
        tartib=tartib,
        ball=ball if ball is not None else item.ball,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def remove_question_from_toplam(db: Session, toplam_id: str, bank_item_id: str, *, teacher_id: str) -> None:
    get_toplam(db, toplam_id, teacher_id=teacher_id)  # egalik tekshiruvi
    deleted = (
        db.query(models.ToplamQuestion)
        .filter(
            models.ToplamQuestion.toplam_id == toplam_id,
            models.ToplamQuestion.bank_item_id == bank_item_id,
        )
        .delete(synchronize_session=False)
    )
    if not deleted:
        raise BankServiceError("Bu savol shu to'plamda topilmadi")
    db.commit()


def reorder_toplam_questions(db: Session, toplam_id: str, *, teacher_id: str, tartib_map: dict[str, int]) -> None:
    """tartib_map: {bank_item_id: yangi_tartib}. Faqat ro'yxatdagi
    savollarning tartibini yangilaydi, qolganlariga tegmaydi.

    YANGI: yangi tartib qiymatlari orasida O'ZARO takrorlanish
    yo'qligi, va to'plamdagi TEGILMAYDIGAN qolgan savollar bilan ham
    to'qnashmasligi tekshiriladi."""
    get_toplam(db, toplam_id, teacher_id=teacher_id)

    # 1) tartib_map ICHIDA o'zaro takrorlanish yo'qligini tekshirish
    new_tartib_values = list(tartib_map.values())
    if len(new_tartib_values) != len(set(new_tartib_values)):
        raise BankServiceError("tartib_map ichida takrorlangan tartib raqami bor")

    links = (
        db.query(models.ToplamQuestion)
        .filter(models.ToplamQuestion.toplam_id == toplam_id)
        .all()
    )
    by_item = {link.bank_item_id: link for link in links}

    # 2) TEGILMAYDIGAN (tartib_map'da yo'q) savollar bilan to'qnashuvni tekshirish
    untouched_tartibs = {
        link.tartib for bank_item_id, link in by_item.items()
        if bank_item_id not in tartib_map
    }
    collision = untouched_tartibs & set(new_tartib_values)
    if collision:
        raise BankServiceError(
            f"Yangi tartib(lar) {sorted(collision)} boshqa (o'zgartirilmayotgan) "
            f"savol(lar) bilan to'qnashadi."
        )

    for bank_item_id, new_tartib in tartib_map.items():
        link = by_item.get(bank_item_id)
        if link is not None:
            link.tartib = new_tartib
    db.commit()


def update_toplam_question_ball(
    db: Session, toplam_id: str, bank_item_id: str, *, teacher_id: str, ball: float,
) -> models.ToplamQuestion:
    get_toplam(db, toplam_id, teacher_id=teacher_id)
    link = (
        db.query(models.ToplamQuestion)
        .filter(
            models.ToplamQuestion.toplam_id == toplam_id,
            models.ToplamQuestion.bank_item_id == bank_item_id,
        )
        .first()
    )
    if link is None:
        raise BankServiceError("Bu savol shu to'plamda topilmadi")
    link.ball = ball
    db.commit()
    db.refresh(link)
    return link


# =============================================================
# 3. Avtomatik to'ldirish (qiyinchilik maqsadiga qarab)
# =============================================================

# Qiyinchilik segmentlari -- difficulty_percent (to'g'ri javob
# bergan foiz) qanchalik YUQORI bo'lsa, savol shunchalik OSON degani.
# Chegaralar bir-biriga TEGMAYDI (yarim-ochiq oraliq): masalan aynan
# 70.0% -- "oson" segmentiga tushadi, "o'rtacha"ga emas (agar ikkala
# tomon ham >=/<= bo'lsa, 70.0 ikkala segmentga ham "mos" bo'lib
# qolardi -- bu band bo'yicha noaniqlik keltirib chiqaradi).
_DIFFICULTY_BANDS = {
    "oson": (70.0, 100.0),      # [70, 100]
    "ortacha": (40.0, 70.0),    # [40, 70)
    "qiyin": (0.0, 40.0),       # [0, 40)
}


@dataclass
class AutoFillReport:
    """Avtomatik to'ldirish natijasi -- nechta savol REJALASHTIRILGAN
    va nechtasi HAQIQATDA topilgan/qo'shilgan, segment bo'yicha. UI'da
    "50 tadan 42 tasi topildi, 8 tasi yetishmadi" kabi ko'rsatish
    uchun."""
    added: list[models.ToplamQuestion] = field(default_factory=list)
    shortfall: dict[str, int] = field(default_factory=dict)  # {"qiyin": 5} -- 5 ta yetishmadi
    used_unrated_fallback: int = 0  # baholanmagan savollardan qancha ishlatildi (yetishmovchilikni to'ldirish uchun)


def auto_fill_toplam(
    db: Session,
    toplam_id: str,
    *,
    teacher_id: str,
    fan_id: str,
    qiyinchilik_maqsadi: dict[str, float],
    exclude_existing: bool = True,
) -> AutoFillReport:
    """
    To'plamning savollar_soni'ga qarab, berilgan fan bo'yicha bank'dan
    savol tanlab, ToplamQuestion sifatida qo'shadi.

    qiyinchilik_maqsadi -- masalan {"oson": 30, "ortacha": 50, "qiyin": 20}
    (FOIZLARDA, yig'indisi 100 bo'lishi shart emas -- nisbatan
    hisoblanadi, lekin aniqlik uchun 100ga yaqin bo'lgani ma'qul).

    STRATEGIYA (yetishmovchilik bo'lganda):
      1. Har segment uchun mos KELGAN (baholangan) savollardan tanlab
         olinadi.
      2. Agar biror segmentda savol YETMASA -- avval BOSHQA
         segmentlardan ORTIQCHA (talab qilingandan ko'p) mavjud
         bo'lgan savollar bilan TO'LDIRILMAYDI (bu qiyinchilik
         taqsimotini buzadi) -- buning o'rniga navbatdagi qadamda
         baholanmagan (difficulty_percent IS NULL) savollar bilan
         to'ldiriladi, chunki ular "noma'lum qiyinchilikda" va
         hech bir segmentni sun'iy og'irlashtirmaydi.
      3. Agar baholanmagan ham yetmasa -- report.shortfall'da qoldiq
         ko'rsatiladi, TO'LDIRILMAYDI (chaqiruvchi UI orqali
         o'qituvchiga "N ta savol yetishmadi, band qo'lda to'ldiring"
         deb ko'rsatishi kerak -- soxta/tasodifiy savol bilan
         to'ldirmaslik ataylab, sifat pasaymasin uchun).
    """
    toplam = get_toplam(db, toplam_id, teacher_id=teacher_id)
    target_total = toplam.savollar_soni

    total_weight = sum(qiyinchilik_maqsadi.values()) or 1.0
    target_counts: dict[str, int] = {}
    for band in _DIFFICULTY_BANDS:
        pct = qiyinchilik_maqsadi.get(band, 0.0)
        target_counts[band] = round(target_total * (pct / total_weight))

    # Yaxlitlashdan kelib chiqadigan +-1 farqni "qiyin"ga qo'shib/ayirib tuzatamiz
    diff = target_total - sum(target_counts.values())
    if diff != 0:
        target_counts["qiyin"] = max(0, target_counts["qiyin"] + diff)

    already_in_toplam = set()
    if exclude_existing:
        already_in_toplam = {
            row[0]
            for row in db.query(models.ToplamQuestion.bank_item_id)
            .filter(models.ToplamQuestion.toplam_id == toplam_id)
            .all()
        }

    existing_max_tartib = (
        db.query(func.max(models.ToplamQuestion.tartib))
        .filter(models.ToplamQuestion.toplam_id == toplam_id)
        .scalar()
        or 0
    )
    next_tartib = existing_max_tartib + 1

    report = AutoFillReport()
    picked_ids: set[str] = set()

    for band, (lo, hi) in _DIFFICULTY_BANDS.items():
        need = target_counts.get(band, 0)
        if need <= 0:
            continue

        is_top_band = (band == "oson")  # eng yuqori segment -- hi (100) ham kiradi
        query = (
            db.query(models.QuestionBankItem)
            .filter(
                models.QuestionBankItem.teacher_id == teacher_id,
                models.QuestionBankItem.fan_id == fan_id,
                models.QuestionBankItem.difficulty_percent.isnot(None),
                models.QuestionBankItem.difficulty_percent >= lo,
            )
        )
        query = (
            query.filter(models.QuestionBankItem.difficulty_percent <= hi)
            if is_top_band
            else query.filter(models.QuestionBankItem.difficulty_percent < hi)
        )
        candidates = (
            query.order_by(func.random())
            .limit(need + len(already_in_toplam))  # ehtiyot zaxirasi bilan olib, keyin filterlaymiz
            .all()
        )

        chosen = [
            c for c in candidates
            if c.id not in already_in_toplam and c.id not in picked_ids
        ][:need]

        for item in chosen:
            link = models.ToplamQuestion(
                toplam_id=toplam.id, bank_item_id=item.id,
                tartib=next_tartib, ball=item.ball,
            )
            db.add(link)
            report.added.append(link)
            picked_ids.add(item.id)
            next_tartib += 1

        shortfall = need - len(chosen)
        if shortfall > 0:
            report.shortfall[band] = shortfall

    # 2-bosqich: yetishmagan sonni baholanmagan savollar bilan to'ldirish
    total_shortfall = sum(report.shortfall.values())
    if total_shortfall > 0:
        fallback_candidates = (
            db.query(models.QuestionBankItem)
            .filter(
                models.QuestionBankItem.teacher_id == teacher_id,
                models.QuestionBankItem.fan_id == fan_id,
                models.QuestionBankItem.difficulty_percent.is_(None),
            )
            .order_by(func.random())
            .limit(total_shortfall + len(already_in_toplam))
            .all()
        )
        fallback_chosen = [
            c for c in fallback_candidates
            if c.id not in already_in_toplam and c.id not in picked_ids
        ][:total_shortfall]

        for item in fallback_chosen:
            link = models.ToplamQuestion(
                toplam_id=toplam.id, bank_item_id=item.id,
                tartib=next_tartib, ball=item.ball,
            )
            db.add(link)
            report.added.append(link)
            picked_ids.add(item.id)
            next_tartib += 1
            report.used_unrated_fallback += 1

        # shortfall'ni haqiqiy to'ldirilgan songa qarab kamaytiramiz
        remaining = total_shortfall - len(fallback_chosen)
        if remaining <= 0:
            report.shortfall = {}
        else:
            # Nisbatan taqsimlab qoldiq ko'rsatamiz (aniq segment
            # ma'lumoti endi muhim emas, jami qoldiq yetarli)
            report.shortfall = {"jami": remaining}

    db.commit()
    for link in report.added:
        db.refresh(link)
    return report


# =============================================================
# 4. "KO'PRIK" -- Toplam -> eski Question dict formati
# =============================================================

def toplam_to_question_dicts(db: Session, toplam_id: str, *, teacher_id: str) -> list[dict]:
    """
    app/services/exam_service.py'dagi _question_to_dict() bilan
    AYNAN BIR XIL kalitlarni qaytaradi -- shu tufayli
    randomization.build_shuffled_booklet() bu ro'yxatni eski
    Variant->Question ro'yxatidan farqlay olmaydi (funksiya nuqtai
    nazaridan ular bir xil "shakl").

    Farqlar:
      - "id" -- bank_item_id (Toplam ichidagi savolning ASL ID'si,
        Question.id EMAS). answer_key['original_question_id'] shu
        qiymatni oladi -- keyinchalik natija tekshirilganda
        record_bank_attempt() aynan shu ID orqali QuestionBankItem'ni
        topadi.
      - "tartib"/"ball" -- ToplamQuestion'dan olinadi (bank_item'ning
        o'zidagi standart qiymatlardan EMAS -- chunki bitta savol
        turli to'plamda boshqa tartib/ball bilan qatnashishi mumkin,
        1-qismdagi arxitektura qaroriga qarang).

    MUHIM: qaytarilgan ro'yxat "tartib" bo'yicha SARALANMAGAN --
    randomization.py o'zi ichida saralaydi (_group_into_blocks), shu
    yerda qayta saralash shart emas.
    """
    toplam = get_toplam(db, toplam_id, teacher_id=teacher_id)

    rows = (
        db.query(models.ToplamQuestion, models.QuestionBankItem)
        .join(models.QuestionBankItem, models.ToplamQuestion.bank_item_id == models.QuestionBankItem.id)
        .filter(models.ToplamQuestion.toplam_id == toplam.id)
        .all()
    )

    if not rows:
        raise BankServiceError("Bu to'plamda hali savol yo'q")

    result: list[dict] = []
    for link, item in rows:
        result.append({
            "id": item.id,  # bank_item_id -- pastdagi izohga qarang
            "tartib": link.tartib,
            "fan": item.fan.name,  # YANGI: fan endi relationship (Fan obyekti), .name orqali string olamiz
            "ball": link.ball,
            "savol_html": item.savol_html,
            "savol_rasm_url": item.savol_rasm_url,
            "jadval_html": item.jadval_html,
            "variant_a_html": item.variant_a_html,
            "variant_b_html": item.variant_b_html,
            "variant_c_html": item.variant_c_html,
            "variant_d_html": item.variant_d_html,
            "togri_javob": item.togri_javob,
        })
    return result


def sync_attempts_for_exam_student(db: Session, exam_student: models.ExamStudent, raw_answers: dict) -> None:
    """
    Toplam ASOSIDAGI imtihon uchun -- exam_student.answer_key_json
    ichidagi har bir savolning `original_question_id`si (ko'prik
    funksiyasi shu maydonga bank_item_id qo'ygan edi) bo'yicha
    QuestionAttempt yozadi va QuestionBankItem statistikasini
    yangilaydi.

    MUHIM -- IDEMPOTENT: bu funksiya qayta chaqirilishi mumkin
    (masalan o'qituvchi noaniq/MULTI javoblarni qo'lda tuzatgandan
    keyin natija qayta hisoblansa). Shuning uchun avval SHU
    exam_student uchun oldin yozilgan attempt'larni o'chirib, keyin
    qayta yozadi -- aks holda bitta talabaning bitta savoli statistika
    hisobida bir necha marta qo'shilib, "necha marta ko'rsatilgan"
    sonini soxta oshirib yuborardi.

    Faqat exam_student.exam.toplam_id BERILGAN bo'lganda chaqirilishi
    kerak -- chaqiruvchi (omr_service.py) shuni tekshiradi. Eski
    (Variant asosidagi) imtihonlar uchun bu funksiya ISHLATILMAYDI --
    ularda answer_key['original_question_id'] Question.id, bank_item_id
    EMAS.
    """
    answer_key = exam_student.answer_key_json or {}
    bank_item_ids = {
        meta.get("original_question_id")
        for meta in answer_key.values()
        if meta.get("original_question_id")
    }
    if not bank_item_ids:
        return

    # 1) Eski yozuvlarni tozalash (idempotentlik uchun)
    db.query(models.QuestionAttempt).filter(
        models.QuestionAttempt.exam_student_id == exam_student.id,
        models.QuestionAttempt.bank_item_id.in_(bank_item_ids),
    ).delete(synchronize_session=False)

    # 2) Yangi yozuvlarni qo'shish (bu yerda record_attempts_bulk()ning
    #    o'zini ISHLATMAYMIZ, chunki u statistikaga DELTA qo'shadi --
    #    o'chirilgan eski yozuvning ta'sirini ayirmaydi. Shuning uchun
    #    xom QuestionAttempt qatorlarini to'g'ridan-to'g'ri yozib,
    #    keyin recompute_difficulty() bilan HAR DOIM asl holatdan qayta
    #    hisoblaymiz -- bu qayta-tekshirish qancha marta bo'lishidan
    #    qat'iy nazar har doim TO'G'RI natija beradi.
    for tartib_str, meta in answer_key.items():
        bank_item_id = meta.get("original_question_id")
        if not bank_item_id:
            continue
        given = raw_answers.get(tartib_str)
        is_correct = None
        if given not in (None, "MULTI"):
            is_correct = (given == meta["correct_letter_shown_to_student"])

        db.add(models.QuestionAttempt(
            exam_student_id=exam_student.id,
            bank_item_id=bank_item_id,
            given_letter=given if given != "MULTI" else None,
            is_correct=is_correct,
        ))

    db.commit()

    # 3) Ta'sirlangan har bir savol uchun statistikani asl
    #    QuestionAttempt yozuvlaridan qayta hisoblaymiz
    for bank_item_id in bank_item_ids:
        recompute_difficulty(db, bank_item_id)


# =============================================================
# 5. QuestionAttempt yozish + qiyinchilik statistikasini yangilash
# =============================================================

def record_attempt(
    db: Session,
    *,
    exam_student_id: str,
    given_letter: str | None,
    is_correct: bool | None,
    question_id: str | None = None,
    bank_item_id: str | None = None,
) -> models.QuestionAttempt:
    """
    Bitta savolga berilgan javobni yozadi. `question_id` (eski tizim)
    yoki `bank_item_id` (yangi tizim) dan FAQAT BITTASI berilishi
    shart -- ikkalasi ham yoki hech biri berilsa xato.

    Agar `bank_item_id` berilgan bo'lsa -- QuestionBankItem'ning
    denormalizatsiya qilingan statistikasi (times_shown/times_correct/
    difficulty_percent) SHU YERDA, bitta tranzaksiyada yangilanadi.
    is_correct=None (bo'sh/noaniq javob) statistikaga QO'SHILMAYDI --
    faqat aniq (True/False) natijalar hisoblanadi.
    """
    if bool(question_id) == bool(bank_item_id):
        raise BankServiceError(
            "question_id yoki bank_item_id dan FAQAT BITTASI berilishi kerak"
        )

    attempt = models.QuestionAttempt(
        exam_student_id=exam_student_id,
        question_id=question_id,
        bank_item_id=bank_item_id,
        given_letter=given_letter,
        is_correct=is_correct,
    )
    db.add(attempt)

    if bank_item_id and is_correct is not None:
        item = db.query(models.QuestionBankItem).filter(
            models.QuestionBankItem.id == bank_item_id
        ).first()
        if item is not None:
            item.times_shown = (item.times_shown or 0) + 1
            if is_correct:
                item.times_correct = (item.times_correct or 0) + 1
            item.difficulty_percent = round(100.0 * item.times_correct / item.times_shown, 1)

    db.commit()
    db.refresh(attempt)
    return attempt


def record_attempts_bulk(
    db: Session, rows: list[dict],
) -> list[models.QuestionAttempt]:
    """record_attempt()ning ko'plab yozuv uchun tezroq varianti --
    bitta imtihon natijasi tekshirilganda odatda 30-90 ta savol
    birdan keladi, har biri uchun alohida commit() qilish sekin
    bo'lardi. `rows` -- record_attempt() bilan bir xil kalitlarga ega
    dict'lar ro'yxati. Bitta commit bilan yakunlanadi."""
    created: list[models.QuestionAttempt] = []
    # bank_item statistikasini xotirada yig'ib, oxirida bitta marta
    # yozamiz (bir xil savol bir nechta marta uchrasa ham to'g'ri
    # ishlashi uchun)
    stat_delta: dict[str, list[int]] = {}  # {bank_item_id: [shown, correct]}

    for row in rows:
        question_id = row.get("question_id")
        bank_item_id = row.get("bank_item_id")
        if bool(question_id) == bool(bank_item_id):
            raise BankServiceError(
                "Har bir yozuvda question_id yoki bank_item_id dan FAQAT BITTASI bo'lishi kerak"
            )

        attempt = models.QuestionAttempt(
            exam_student_id=row["exam_student_id"],
            question_id=question_id,
            bank_item_id=bank_item_id,
            given_letter=row.get("given_letter"),
            is_correct=row.get("is_correct"),
        )
        db.add(attempt)
        created.append(attempt)

        if bank_item_id and row.get("is_correct") is not None:
            shown, correct = stat_delta.get(bank_item_id, [0, 0])
            stat_delta[bank_item_id] = [shown + 1, correct + (1 if row["is_correct"] else 0)]

    if stat_delta:
        items = (
            db.query(models.QuestionBankItem)
            .filter(models.QuestionBankItem.id.in_(stat_delta.keys()))
            .all()
        )
        for item in items:
            shown_delta, correct_delta = stat_delta[item.id]
            item.times_shown = (item.times_shown or 0) + shown_delta
            item.times_correct = (item.times_correct or 0) + correct_delta
            item.difficulty_percent = round(100.0 * item.times_correct / item.times_shown, 1)

    db.commit()
    for attempt in created:
        db.refresh(attempt)
    return created


def recompute_difficulty(db: Session, bank_item_id: str) -> models.QuestionBankItem:
    """Denormalizatsiya qilingan statistika biror sababdan (masalan
    qo'lda ma'lumot o'zgartirilgan, yoki eski xato) haqiqiy
    QuestionAttempt yozuvlaridan chetlashib qolsa -- shundan qayta
    hisoblab to'g'irlaydi."""
    item = db.query(models.QuestionBankItem).filter(
        models.QuestionBankItem.id == bank_item_id
    ).first()
    if item is None:
        raise BankServiceError("Savol topilmadi")

    shown, correct = (
        db.query(
            func.count(models.QuestionAttempt.id),
            func.sum(func.cast(models.QuestionAttempt.is_correct, Integer)),
        )
        .filter(
            models.QuestionAttempt.bank_item_id == bank_item_id,
            models.QuestionAttempt.is_correct.isnot(None),
        )
        .first()
    )
    shown = shown or 0
    correct = correct or 0

    item.times_shown = shown
    item.times_correct = correct
    item.difficulty_percent = round(100.0 * correct / shown, 1) if shown > 0 else None

    db.commit()
    db.refresh(item)
    return item


def recompute_all_difficulties(db: Session, *, teacher_id: str) -> int:
    """Bitta o'qituvchining BARCHA bank savollari uchun
    recompute_difficulty()ni ketma-ket bajaradi. Qaytadi: nechta
    savol qayta hisoblanganini (son)."""
    item_ids = [
        row[0]
        for row in db.query(models.QuestionBankItem.id)
        .filter(models.QuestionBankItem.teacher_id == teacher_id)
        .all()
    ]
    for item_id in item_ids:
        recompute_difficulty(db, item_id)
    return len(item_ids)
