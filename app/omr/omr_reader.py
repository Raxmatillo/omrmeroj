# -*- coding: utf-8 -*-

"""
OMR Answer Sheet Reader
=======================

`omr_generator.py` bilan yaratilgan javoblar varaqasini
(chop etilib, qo'lda belgilangan va rasmga olingan yoki
skanerlangan/PDF holda) o'qiydi.

HOZIRCHA:
    - Faqat qaysi variant (A/B/C/D) belgilanganini
      va necha foiz to'ldirilganini aniqlaydi.
    - Agar varaqda QR kod bo'lsa, uni o'qib terminalda
      ko'rsatadi (masalan varaq/savol ID'si).
    - TO'G'RI / NOTO'G'RI JAVOBNI TEKSHIRMAYDI
      (buni keyingi bosqichda javoblar kaliti bilan
      qo'shamiz).

Kirish formatlari:
    - .jpg / .jpeg / .png / .webp / va h.k. -> to'g'ridan-to'g'ri rasm
    - .pdf -> birinchi sahifa TARGET_DPI bilan rasmga aylantiriladi
      (pdf2image + poppler orqali). PDF odatda telefon kamerasi bilan
      olingan fotoga qaraganda ancha sifatli/tekis bo'lgani uchun
      tavsiya etiladi, lekin skript ikkalasini ham qabul qiladi.

Muhim:
    Bu skript generatordagi ANIQ mm-koordinatalarga
    (marker joylashuvi, ustunlar, qatorlar, bubble radiusi)
    tayanadi. Agar generatordagi joylashuv o'zgarsa,
    quyidagi LAYOUT konstantalarini ham shunga mos
    yangilash kerak.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np


# ============================================================
# LAYOUT KONSTANTALARI
#
# Bular omr_generator.py dagi qiymatlar bilan
# BIR XIL bo'lishi SHART.
# ============================================================

PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0

# Ishlaydigan chop etish DPI'si (perspective-correction
# natijasi shu DPI'ga standartlashtiriladi)
TARGET_DPI = 300
PX_PER_MM = TARGET_DPI / 25.4

OUTPUT_WIDTH = round(PAGE_WIDTH_MM * PX_PER_MM)    # ~2480
OUTPUT_HEIGHT = round(PAGE_HEIGHT_MM * PX_PER_MM)  # ~3508

# Registration markerlar: chap-yuqori burchagi (mm) + o'lcham
MARKER_SIZE_MM = 5.0
MARKER_POSITIONS_MM = {
    "tl": (7.0, 7.0),
    "tr": (198.0, 7.0),
    "bl": (7.0, 285.0),
    "br": (198.0, 285.0),
}

# Javob ustunlari
ANSWER_LETTERS = ["A", "B", "C", "D"]

# 3 ta ustun: (boshlanish_savol, tugash_savol)
QUESTION_GROUPS = [
    (1, 30),
    (31, 60),
    (61, 90),
]

COLUMN_LEFT_MM = [11.0, 56.0, 101.0]
COLUMN_WIDTH_MM = 42.0

ANSWER_TOP_MM = 111.0
HEADER_H_MM = 18.0
ROW_H_MM = 4.25
MAX_ROWS = 30

# Ustundagi A/B/C/D bubble markazlari (column_left'ga nisbatan, mm)
ANSWER_OFFSETS_MM = [16.0, 23.0, 30.0, 37.0]

BUBBLE_RADIUS_MM = 1.75

# PDF'ni rasmga aylantirishda ishlatiladigan fayl kengaytmalari
PDF_EXTENSIONS = {".pdf"}


# ============================================================
# NATIJA MODELLARI
# ============================================================

@dataclass
class OptionResult:
    letter: str
    fill_percentage: float


@dataclass
class QuestionResult:
    question: int
    answer: Optional[str]
    status: str  # "blank" | "marked" | "uncertain"
    options: List[OptionResult]


# ============================================================
# RASMNI / PDF'NI YUKLASH
# ============================================================

def load_image(image_path) -> np.ndarray:
    """
    Kiritilgan fayl kengaytmasiga qarab rasmni yuklaydi.

    - .pdf bo'lsa: pdf2image (poppler) yordamida birinchi sahifa
      TARGET_DPI bilan renderlanadi va OpenCV (BGR) massiviga
      aylantiriladi.
    - Aks holda (.jpg, .png, .webp va h.k.): oddiy cv2.imread.
    """

    path = Path(image_path)
    suffix = path.suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return _load_pdf_first_page(path)

    image = cv2.imread(str(path))

    if image is None:
        raise ValueError(f"Rasmni ochib bo'lmadi: {image_path}")

    return image


def _load_pdf_first_page(pdf_path: Path) -> np.ndarray:

    try:
        from pdf2image import convert_from_path
    except ImportError as exc:
        raise ImportError(
            "PDF fayllarni o'qish uchun 'pdf2image' kutubxonasi va "
            "'poppler-utils' (pdftoppm) kerak. "
            "O'rnatish: pip install pdf2image  (+ poppler-utils tizim paketi)"
        ) from exc

    pages = convert_from_path(str(pdf_path), dpi=TARGET_DPI, first_page=1, last_page=1)

    if not pages:
        raise ValueError(f"PDF'dan sahifa o'qib bo'lmadi: {pdf_path}")

    pil_image = pages[0].convert("RGB")
    rgb_array = np.array(pil_image)

    # PIL -> RGB, OpenCV -> BGR
    bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)

    return bgr_array


def to_gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def make_binary(gray: np.ndarray) -> np.ndarray:
    """
    Yorug'lik bir xil bo'lmagan fotolar uchun adaptive threshold.
    Natija: qalam/marker izlari = 255 (oq), qog'oz = 0 (qora).
    """

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    binary = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        35,
        12,
    )

    return binary


# ============================================================
# QR KOD O'QISH
# ============================================================

def read_qr_code(image: np.ndarray) -> Optional[str]:
    """
    Rasmda QR kod bo'lsa, uni o'qib matn/ID qiymatini qaytaradi.
    Topilmasa None qaytaradi.

    OpenCV'ning o'rnatilgan QRCodeDetector'i ishlatiladi (qo'shimcha
    kutubxona shart emas). QR kod varaqning istalgan joyida bo'lishi
    mumkin — butun rasm bo'ylab qidiradi, aniq koordinataga bog'liq
    emas.
    """

    detector = cv2.QRCodeDetector()

    try:
        # Ba'zi OpenCV versiyalarida bir nechta QR kodni bir yo'la
        # aniqlash mumkin (detectAndDecodeMulti). Avval shuni sinab
        # ko'ramiz, bo'lmasa oddiy detectAndDecode'ga o'tamiz.
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(image)
        if ok:
            values = [v for v in decoded_info if v]
            if values:
                return values[0]
    except (cv2.error, AttributeError):
        pass

    data, points, _ = detector.detectAndDecode(image)

    if data:
        return data

    return None


# ============================================================
# 4 TA REGISTRATSIYA MARKERINI TOPISH
# ============================================================

def _quadrant_of(point: Tuple[float, float], w: int, h: int) -> str:

    px, py = point

    if px < w / 2 and py < h / 2:
        return "tl"

    if px >= w / 2 and py < h / 2:
        return "tr"

    if px < w / 2 and py >= h / 2:
        return "bl"

    return "br"


def find_registration_markers(image: np.ndarray) -> dict:
    """
    Rasmning 4 burchagidagi qora kvadrat markerlarni topadi.

    Har bir burchak (kvadrant) uchun eng burchakka yaqin va
    eng "kvadratsimon" konturni tanlaydi. Bu QR kod, to'ldirilgan
    bubble'lar yoki matn kabi boshqa qora obyektlar bilan
    adashtirib yubormaslik uchun kerak.

    Qaytaradi: {"tl": (x, y), "tr": (x, y), "bl": (x, y), "br": (x, y)}
    Topilmagan burchaklar lug'atda bo'lmaydi.
    """

    gray = to_gray(image)
    h, w = gray.shape

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # MUHIM: global (Otsu) threshold emas, LOKAL (adaptive) threshold
    # ishlatiladi. Fotoda qog'ozdan tashqarida (stol, soya va h.k.)
    # turlicha yorug'lik/rang bo'lishi mumkin — global threshold bunday
    # holda markerni fondan ajrata olmasligi mumkin. Adaptive threshold
    # esa har bir nuqtani FAQAT o'z atrofidagi (qog'oz ustidagi) yorug'lik
    # bilan solishtiradi, shuning uchun fonning rangi/yorug'ligidan
    # deyarli mustaqil ishlaydi.
    block_size = max(15, (min(h, w) // 25) | 1)  # toq son bo'lishi shart

    threshold = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        10,
    )

    # Kichik shovqinlarni tozalash + markerni "yaxlitlash"
    kernel = np.ones((3, 3), np.uint8)
    threshold = cv2.morphologyEx(threshold, cv2.MORPH_CLOSE, kernel)
    threshold = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, kernel)

    # MUHIM: RETR_EXTERNAL EMAS, RETR_LIST ishlatiladi.
    #
    # Fotoda qog'ozdan tashqarida (stol, soya, shovqin) mayda
    # thresholded "dog'lar" bo'lishi mumkin va ular bir-biriga
    # ulanib, butun rasmni ichiga olgan yagona tashqi konturga
    # aylanib qolishi mumkin (marker va boshqa kontent shu tashqi
    # kontur ICHIDA "teshik" sifatida qolib ketadi va RETR_EXTERNAL
    # ularni butunlay ko'rmay qoladi). RETR_LIST esa ierarxiyadan
    # qat'iy nazar barcha konturlarni qaytaradi — filtrlash
    # (o'lcham/nisbat/burchakka yaqinlik) haqiqiy markerni baribir
    # aniq topib beradi.
    contours, _ = cv2.findContours(
        threshold,
        cv2.RETR_LIST,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    image_area = float(w * h)

    # Marker chizilgan (5mm) / sahifa (210mm) nisbati asosida
    # kutilayotgan yuza ulushi (juda keng oraliqda, chunki foto
    # burchaklarida qog'ozdan tashqari fon ham bo'lishi mumkin)
    expected_ratio = (MARKER_SIZE_MM / PAGE_WIDTH_MM) ** 2
    min_area = image_area * expected_ratio * 0.15
    max_area = image_area * expected_ratio * 12.0

    candidates_by_quadrant = {"tl": [], "tr": [], "bl": [], "br": []}

    for contour in contours:

        x, y, bw, bh = cv2.boundingRect(contour)
        area = bw * bh

        if area < min_area or area > max_area:
            continue

        ratio = bw / float(bh)

        if not (0.6 <= ratio <= 1.4):
            continue

        # To'ldirilganlik (kvadratga qanchalik yaqinligi)
        fill_ratio = cv2.contourArea(contour) / float(area + 1e-6)

        if fill_ratio < 0.55:
            continue

        center = (x + bw / 2.0, y + bh / 2.0)
        quadrant = _quadrant_of(center, w, h)

        # Mos burchakka (rasmning haqiqiy burchak nuqtasiga)
        # bo'lgan masofa — bu bilan markerni QR yoki boshqa
        # qora bloklardan ajratamiz.
        corner_point = {
            "tl": (0, 0),
            "tr": (w, 0),
            "bl": (0, h),
            "br": (w, h),
        }[quadrant]

        distance = (
            (center[0] - corner_point[0]) ** 2
            + (center[1] - corner_point[1]) ** 2
        ) ** 0.5

        candidates_by_quadrant[quadrant].append(
            {
                "center": center,
                "distance": distance,
                "fill_ratio": fill_ratio,
            }
        )

    markers = {}

    for quadrant, candidates in candidates_by_quadrant.items():

        if not candidates:
            continue

        # Burchakka eng yaqinini tanlaymiz
        best = min(candidates, key=lambda c: c["distance"])
        markers[quadrant] = best["center"]

    return markers


# ============================================================
# PERSPECTIVE CORRECTION
# ============================================================

def perspective_correct(
    image: np.ndarray,
    markers: dict,
) -> np.ndarray:
    """
    Rasm qiyshiq / burchakdan olingan bo'lsa ham,
    4 ta marker asosida uni standart A4 canvasga
    (OUTPUT_WIDTH x OUTPUT_HEIGHT, ya'ni TARGET_DPI) tekislaydi.

    MUHIM: markerlar canvas BURCHAKLARIGA emas, balki
    ularning HAQIQIY mm joylashuviga mos nuqtalarga
    proyeksiya qilinadi. Shu sababli tekislashdan keyin
    har qanday mm koordinatani PX_PER_MM bilan ko'paytirib,
    to'g'ridan-to'g'ri piksel koordinataga aylantirish mumkin.
    """

    required = ["tl", "tr", "bl", "br"]

    missing = [k for k in required if k not in markers]

    if missing:
        raise ValueError(
            f"Quyidagi markerlar topilmadi: {missing}. "
            f"Topilganlar: {list(markers.keys())}"
        )

    src = np.array(
        [
            markers["tl"],
            markers["tr"],
            markers["br"],
            markers["bl"],
        ],
        dtype=np.float32,
    )

    def marker_center_px(key: str) -> Tuple[float, float]:
        left, top = MARKER_POSITIONS_MM[key]
        cx_mm = left + MARKER_SIZE_MM / 2
        cy_mm = top + MARKER_SIZE_MM / 2
        return (cx_mm * PX_PER_MM, cy_mm * PX_PER_MM)

    dst = np.array(
        [
            marker_center_px("tl"),
            marker_center_px("tr"),
            marker_center_px("br"),
            marker_center_px("bl"),
        ],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(src, dst)

    warped = cv2.warpPerspective(
        image,
        matrix,
        (OUTPUT_WIDTH, OUTPUT_HEIGHT),
    )

    return warped


# ============================================================
# BITTA BUBBLE ICHIDAGI TO'LDIRILGANLIKNI O'LCHASH
# ============================================================

def get_fill_percentage(
    binary: np.ndarray,
    center_x_px: int,
    center_y_px: int,
    radius_px: float,
    inner_ratio: float = 0.72,
) -> float:
    """
    `binary` — make_binary() natijasi (ink = 255, qog'oz = 0).

    Bubble radiusining ichki (inner_ratio) qismidagi doiraviy
    maska orqali ink foizini hisoblaydi. Doira chizig'ining
    o'zi (printer chizgan aylana) hisobga olinmasligi uchun
    radius biroz kichraytiriladi.
    """

    r = max(2, int(round(radius_px * inner_ratio)))

    h, w = binary.shape

    x1 = max(0, center_x_px - r)
    x2 = min(w, center_x_px + r)
    y1 = max(0, center_y_px - r)
    y2 = min(h, center_y_px + r)

    if x2 <= x1 or y2 <= y1:
        return 0.0

    roi = binary[y1:y2, x1:x2]

    mask = np.zeros(roi.shape, dtype=np.uint8)

    mask_center = (
        center_x_px - x1,
        center_y_px - y1,
    )

    cv2.circle(mask, mask_center, r, 255, -1)

    ink = cv2.bitwise_and(roi, mask)

    total_mask_px = int(np.count_nonzero(mask))

    if total_mask_px == 0:
        return 0.0

    ink_px = int(np.count_nonzero(ink))

    return round(ink_px / total_mask_px * 100, 2)


# ============================================================
# BITTA SAVOLNI TEKSHIRISH
# ============================================================

def detect_question(
    binary: np.ndarray,
    question_number: int,
    centers_px: List[Tuple[int, int]],
    radius_px: float,
    blank_threshold: float = 15.0,
    marked_threshold: float = 32.0,
    min_margin: float = 8.0,
) -> QuestionResult:
    """
    Har bir variant uchun to'ldirilganlik foizini hisoblaydi va
    natijaga qarab holatni belgilaydi.

    MUHIM (shovqinni bo'shdan ajratish):
        Faqat "eng yuqori foiz 15% dan katta" degan shart YETARLI
        EMAS — qog'oz g'adir-budurligi, soya, JPEG siqilishi kabi
        sabablarga ko'ra to'liq bo'sh savolda ham barcha 4 variant
        taxminan bir xil (masalan 16%, 14%, 13%, 11%) past qiymat
        olishi mumkin. Haqiqiy belgilangan bubble esa boshqalardan
        SEZILARLI farq qiladi (masalan 45% vs 12%).

        Shu sababli eng yuqori va ikkinchi eng yuqori variant
        orasidagi FARQ (margin) ham tekshiriladi:
          - agar eng yuqori qiymat past bo'lsa VA margin kichik
            bo'lsa -> bu shovqin, demak BO'SH.
          - agar eng yuqori qiymat baland bo'lsa-yu, margin kichik
            bo'lsa -> ehtimol ikkita bubble belgilangan (yoki
            noaniq) -> NOANIQ, qo'lda tekshirish kerak.
    """

    options: List[OptionResult] = []

    for letter, (cx, cy) in zip(ANSWER_LETTERS, centers_px):

        percentage = get_fill_percentage(binary, cx, cy, radius_px)

        options.append(OptionResult(letter=letter, fill_percentage=percentage))

    ranked = sorted(options, key=lambda o: o.fill_percentage, reverse=True)
    best = ranked[0]
    second = ranked[1]
    margin = best.fill_percentage - second.fill_percentage

    if best.fill_percentage < blank_threshold:
        # Hech qanday jiddiy ink yo'q -> aniq bo'sh
        answer = None
        status = "blank"

    elif margin < min_margin:
        if best.fill_percentage < marked_threshold:
            # Past qiymatlar + kichik margin -> qog'oz/skan shovqini,
            # aslida hech biri belgilanmagan
            answer = None
            status = "blank"
        else:
            # Baland qiymatlar + kichik margin -> ehtimol 2 ta bubble
            # belgilangan yoki chizilishi noaniq -> qo'lda tekshirish
            answer = best.letter
            status = "uncertain"

    elif best.fill_percentage >= marked_threshold:
        answer = best.letter
        status = "marked"

    else:
        answer = best.letter
        status = "uncertain"

    return QuestionResult(
        question=question_number,
        answer=answer,
        status=status,
        options=options,
    )


# ============================================================
# BUTUN JAVOB VARAQASINI O'QISH
# ============================================================

def _question_centers_px(question_number: int) -> List[Tuple[int, int]]:
    """
    Berilgan savol raqami uchun A/B/C/D bubble markazlarini
    (piksel, TARGET_DPI asosida) qaytaradi.
    """

    # Qaysi ustun / qatorga tegishli ekanini aniqlash
    for column_index, (start, end) in enumerate(QUESTION_GROUPS):

        if start <= question_number <= end:

            row_index = question_number - start

            column_left = COLUMN_LEFT_MM[column_index]

            center_y_mm = (
                ANSWER_TOP_MM
                + HEADER_H_MM
                + row_index * ROW_H_MM
                + ROW_H_MM / 2
            )

            centers = []

            for offset in ANSWER_OFFSETS_MM:

                center_x_mm = column_left + offset

                centers.append(
                    (
                        int(round(center_x_mm * PX_PER_MM)),
                        int(round(center_y_mm * PX_PER_MM)),
                    )
                )

            return centers

    raise ValueError(f"Noma'lum savol raqami: {question_number}")


def detect_answer_sheet(image_path) -> dict:
    """
    Javoblar varaqasini o'qiydi va har bir savol uchun:
      - qaysi variant belgilanganini
      - necha foiz to'ldirilganini
    aniqlaydi.

    Fayl .pdf, .jpg, .png va boshqa keng tarqalgan rasm
    formatlarida bo'lishi mumkin (load_image ichida avtomatik
    aniqlanadi).

    TO'G'RI / NOTO'G'RI TEKSHIRILMAYDI.
    """

    image = load_image(image_path)

    # QR kodni tekislashdan OLDIN, asl rasmdan o'qishga harakat
    # qilamiz (agar tekislash biroz kesib tashlasa ham QR omon qoladi).
    qr_data = read_qr_code(image)

    if qr_data:
        print(f"QR kod topildi -> Varaq ID: {qr_data}")
    else:
        print("QR kod topilmadi (yoki varaqda QR kod yo'q).")

    markers = find_registration_markers(image)

    print(f"Topilgan markerlar: {len(markers)}/4  ({list(markers.keys())})")

    if len(markers) == 4:
        print("Perspective correction bajarilmoqda...")
        warped = perspective_correct(image, markers)
    else:
        print(
            "OGOHLANTIRISH: 4 ta marker topilmadi. "
            "Natija noaniq bo'lishi mumkin. "
            "Rasm tekislanmasdan (asl holida) ishlanadi — "
            "bu holatda rasm to'g'ridan-to'g'ri OUTPUT o'lchamiga "
            "moslashtiriladi, bu koordinatalarni siljitishi mumkin."
        )
        warped = cv2.resize(image, (OUTPUT_WIDTH, OUTPUT_HEIGHT))

    # Agar QR kod tekislashdan oldin topilmagan bo'lsa, tekislangan
    # (kattaroq, tozaroq) rasmda yana bir bor sinab ko'ramiz.
    if not qr_data:
        qr_data = read_qr_code(warped)
        if qr_data:
            print(f"QR kod topildi (tekislangan rasmdan) -> Varaq ID: {qr_data}")

    gray = to_gray(warped)
    binary = make_binary(gray)

    radius_px = BUBBLE_RADIUS_MM * PX_PER_MM

    results: List[QuestionResult] = []

    for start, end in QUESTION_GROUPS:

        for question_number in range(start, end + 1):

            centers = _question_centers_px(question_number)

            result = detect_question(
                binary,
                question_number,
                centers,
                radius_px,
            )

            results.append(result)

    marked = [r for r in results if r.status == "marked"]
    uncertain = [r for r in results if r.status == "uncertain"]
    blank = [r for r in results if r.status == "blank"]

    return {
        "sheet_id": qr_data,
        "total_questions": len(results),
        "marked_count": len(marked),
        "uncertain_count": len(uncertain),
        "blank_count": len(blank),
        "marked_percentage": round(len(marked) / len(results) * 100, 2),
        "questions": results,
        "warped_image": warped,
        "binary_image": binary,
    }


# ============================================================
# NATIJANI CHIROYLI CHIQARISH
# ============================================================

def print_report(report: dict):

    print()
    print("=" * 60)
    if report.get("sheet_id"):
        print(f"VARAQ ID (QR):         {report['sheet_id']}")
    print(f"JAMI SAVOLLAR:        {report['total_questions']}")
    print(f"BELGILANGAN:          {report['marked_count']}")
    print(f"NOANIQ (uncertain):   {report['uncertain_count']}")
    print(f"BO'SH:                {report['blank_count']}")
    print(f"TO'LDIRILGANLIK:      {report['marked_percentage']}%")
    print("=" * 60)

    for start, end in QUESTION_GROUPS:

        print(f"\n--- Savollar {start}-{end} ---")

        for result in report["questions"]:

            if not (start <= result.question <= end):
                continue

            options_str = ", ".join(
                f"{o.letter}={o.fill_percentage:.1f}%"
                for o in result.options
            )

            answer_str = result.answer if result.answer else "-"

            flag = ""
            if result.status == "uncertain":
                flag = "  <-- NOANIQ, qo'lda tekshiring"

            print(
                f"  {result.question:>2}) Javob: {answer_str}  "
                f"[{options_str}]{flag}"
            )


# ============================================================
# DEBUG: TOPILGAN NATIJALARNI RASMGA CHIZIB CHIQISH
# ============================================================

def draw_debug_overlay(report: dict, output_path: str):
    """
    Tekislangan rasm ustiga har bir bubble uchun aniqlangan
    holatni ranglar bilan belgilaydi:

        Yashil  = belgilangan (marked)
        Sariq   = noaniq (uncertain) — qo'lda tekshirish kerak
        Kulrang = bo'sh (blank)

    Bu orqali natijani ko'zdan kechirib, dastur to'g'ri
    ishlaganini tasdiqlash mumkin.
    """

    overlay = report["warped_image"].copy()
    radius_px = int(round(BUBBLE_RADIUS_MM * PX_PER_MM))

    color_map = {
        "marked": (0, 170, 0),
        "uncertain": (0, 200, 255),
        "blank": (180, 180, 180),
    }

    for result in report["questions"]:

        centers = _question_centers_px(result.question)

        for letter, (cx, cy) in zip(ANSWER_LETTERS, centers):

            is_chosen = (result.answer == letter)

            color = color_map[result.status] if is_chosen else (210, 210, 210)
            thickness = 3 if is_chosen else 1

            cv2.circle(overlay, (cx, cy), radius_px, color, thickness)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), overlay)

    return output_path


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    # Endi .jpg/.png bilan bir qatorda .pdf ham beriladi:
    #   image_path = "javoblar_varaqasi_belgilangan.pdf"
    image_path = "javoblar_varaqasi.jpg"

    report = detect_answer_sheet(image_path)

    print_report(report)

    debug_path = draw_debug_overlay(report, "output/debug_overlay.jpg")

    print(f"\nDebug rasm saqlandi: {debug_path}")