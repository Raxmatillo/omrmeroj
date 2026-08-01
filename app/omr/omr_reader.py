# -*- coding: utf-8 -*-

"""
OMR Answer Sheet Reader
=======================

`answer_sheet_generator.py` bilan yaratilgan javoblar varaqasini
(chop etilib, qo'lda belgilangan va rasmga olingan yoki
skanerlangan/PDF holda) o'qiydi.

YANGILANISH (aniqlik uchun, telefon fotolariga mo'ljallangan):

    1. SUBPIXEL MARKER MARKAZI -- registratsiya markerlarining markazi
       endi cv2.boundingRect() emas, balki cv2.moments() (konturning
       og'irlik markazi) orqali topiladi. Bu bir necha piksellik
       xatoni kamaytiradi -- va bu xato butun sahifa bo'ylab
       perspective-correction orqali proporsional kattayib ketadi.

    2. TIMING TRACK -- answer_sheet_generator.py endi har bir qator
       uchun kichik siyoh belgisi chizadi (ustunning chap chetida).
       Reader bubble y-pozitsiyasini ARIFMETIK FORMULA bilan hisoblash
       o'rniga, shu belgilarning HAQIQIY markazlarini topadi
       (find_timing_marks()). Bu -- global homography'dagi kichik
       xatoning pastki qatorlarda (markerdan uzoqda) katta siljishga
       aylanib ketishining oldini oladi. Eski (timing-track'siz)
       varaqlar bilan ham ishlaydi -- agar aniq MAX_ROWS ta belgi
       topilmasa, arifmetik formulaga avtomatik qaytadi.

    3. LOCAL BUBBLE REFINEMENT (Hough) -- har bir qatorda X o'qi
       bo'yicha ham arifmetik formulaga to'liq ishonish o'rniga,
       kichik oyna ichida haqiqiy doiralar (cv2.HoughCircles) qidirib,
       eng yaqinini formulaning o'rniga qo'yadi. Agar hech narsa
       topilmasa (masalan juda xira foto), formulaning o'zi
       ishlatiladi -- shuning uchun bu qadam hech qachon natijani
       yomonlashtirmaydi, faqat yaxshilaydi yoki o'zgarishsiz qoldiradi.

    4. RASM SIFATINI TEKSHIRISH -- juda xira (blur) fotolar aniq
       ogohlantirish bilan qaytariladi (`quality_warnings`), shunda
       botda foydalanuvchiga "qayta suratga oling" deb aytish mumkin,
       aksincha dastur sukut bilan noto'g'ri natija bermaydi.

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
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


from typing import Optional
import logging
from PIL import Image
# Image.MAX_IMAGE_PIXELS = 200_000_000  # 200 MP gacha ruxsat



logger = logging.getLogger(__name__)

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False
    logger.warning("pyzbar o‘rnatilmagan, QR kodni faqat OpenCV orqali o‘qish mumkin.")

# ============================================================
# LAYOUT KONSTANTALARI
#
# Bular answer_sheet_generator.py dagi qiymatlar bilan
# BIR XIL bo'lishi SHART.
# ============================================================

PAGE_WIDTH_MM = 210.0
PAGE_HEIGHT_MM = 297.0

# Ishlaydigan chop etish DPI'si (perspective-correction
# natijasi shu DPI'ga standartlashtiriladi)
TARGET_DPI = 400
PX_PER_MM = TARGET_DPI / 25.4

OUTPUT_WIDTH = round(PAGE_WIDTH_MM * PX_PER_MM)    # ~2480
OUTPUT_HEIGHT = round(PAGE_HEIGHT_MM * PX_PER_MM)  # ~3508

# Registration markerlar: chap-yuqori burchagi (mm) + o'lcham.
# MARKER_SIZE_MM -- answer_sheet_generator.py dagi
# REGISTRATION_MARKER_SIZE_MM bilan BIR XIL bo'lishi shart (8mm).
MARKER_SIZE_MM = 8.0
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

# Timing track -- answer_sheet_generator.py dagi TIMING_MARK_OFFSET_MM /
# TIMING_MARK_SIZE_MM bilan BIR XIL bo'lishi shart.
TIMING_MARK_OFFSET_MM = 1.6
TIMING_MARK_SIZE_MM = 1.4

# PDF'ni rasmga aylantirishda ishlatiladigan fayl kengaytmalari
PDF_EXTENSIONS = {".pdf"}

# Rasm sifatini tekshirish -- Laplacian variance shu qiymatdan past
# bo'lsa, foto "juda xira" deb hisoblanadi (natija baribir qaytariladi,
# lekin ogohlantirish bilan).
BLUR_VARIANCE_THRESHOLD = 80 #60.0

# ============================================================
# TEST VARIANTI bubble maydoni -- app/omr/answer_sheet_generator.py
# dagi bir xil nomdagi konstantalar bilan ANIQ BIR XIL bo'lishi SHART.
# ============================================================
VARIANT_BUBBLE_XS_MM = [133.0, 151.0, 169.0, 187.0]
VARIANT_BUBBLE_Y_MM = 102.0
VARIANT_BUBBLE_RADIUS_MM = 2.2
VARIANT_TIMING_MARK_OFFSET_MM = 3.6
VARIANT_TIMING_MARK_SIZE_MM = 1.4
MAX_PAPER_VARIANTS = len(VARIANT_BUBBLE_XS_MM)  # 4


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
    # Haqiqatda ishlatilgan (refine qilingan yoki arifmetik) markaz
    # koordinatalari -- debug overlay va keyingi tahlil uchun saqlanadi.
    centers_px: Optional[List[Tuple[int, int]]] = None


# ============================================================
# RASMNI / PDF'NI YUKLASH
# ============================================================

def load_image(image_path, dpi: int = 400) -> np.ndarray:
    path = Path(image_path)
    if path.suffix.lower() in PDF_EXTENSIONS:
        image = _load_pdf_first_page(path, dpi=dpi)
    else:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Rasmni ochib bo'lmadi: {image_path}")
    
    # Agar juda katta bo'lsa, kichraytiramiz
    h, w = image.shape[:2]
    max_pixels = 30_000_000  # 30 MP yetarli (A4 300 DPI ~8.7 MP)
    if h * w > max_pixels:
        scale = (max_pixels / (h * w)) ** 0.5
        new_w = int(w * scale)
        new_h = int(h * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        # Log qo'shish mumkin
        logger.info(f"Rasm o'lchami {w}x{h} → {new_w}x{new_h} gacha kichraytirildi")
    return image


def _load_pdf_first_page(pdf_path: Path, dpi: int = 400) -> np.ndarray:

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
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    block_size = max(15, (min(gray.shape) // 20) | 1)  # toq
    binary = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        8,  # C ni 8 ga tushiring
    )
    return binary

# def make_binary(gray: np.ndarray) -> np.ndarray:
#     """
#     Yorug'lik bir xil bo'lmagan fotolar uchun adaptive threshold.
#     Natija: qalam/marker izlari = 255 (oq), qog'oz = 0 (qora).
#     """

#     blurred = cv2.GaussianBlur(gray, (5, 5), 0)

#     binary = cv2.adaptiveThreshold(
#         blurred,
#         255,
#         cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#         cv2.THRESH_BINARY_INV,
#         35,
#         12,
#     )

#     return binary


# ============================================================
# RASM SIFATINI TEKSHIRISH
# ============================================================

def assess_image_quality(gray: np.ndarray) -> List[str]:
    """
    Fotoning aniq muammolarini oldindan aniqlaydi -- shu bilan dastur
    sukut bilan noto'g'ri natija berish o'rniga, foydalanuvchiga
    "qayta suratga oling" deyish imkoniyatiga ega bo'ladi.

    Hozircha faqat blur (xiralik) tekshiriladi -- Laplacian variance
    past bo'lsa, foto muhim detallarni (bubble chegaralari) yo'qotgan
    bo'lishi mumkin.
    """

    warnings: List[str] = []

    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()

    if blur_score < BLUR_VARIANCE_THRESHOLD:
        warnings.append(
            "Rasm xira (blur) ko'rinadi -- natija noaniq bo'lishi mumkin. "
            "Iltimos yaxshiroq yorug'likda, qo'lni tebratmasdan qayta "
            "suratga oling."
        )

    return warnings


# ============================================================
# QR KOD O'QISH
# ============================================================


def _enhance_for_qr(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    return clahe.apply(gray)

def read_qr_code(image: np.ndarray) -> Optional[str]:
    """
    Rasmda QR kodni topish uchun bir nechta usulni sinab ko‘radi:
      1. OpenCV QRCodeDetector (tez, o‘rnatilgan)
      2. pyzbar (aniqroq, lekin sekinroq)

    Agar biron usul topilsa, matn/ID qaytaradi, aks holda None.
    """
    # 1. OpenCV QRCodeDetector
    detector = cv2.QRCodeDetector()
    try:
        # Multi detektorni sinab ko‘ramiz
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(image)
        if ok and decoded_info:
            values = [v for v in decoded_info if v]
            if values:
                return values[0]
    except (cv2.error, AttributeError):
        pass

    # Oddiy detectAndDecode
    try:
        data, points, _ = detector.detectAndDecode(image)
        if data:
            return data
    except cv2.error:
        pass

    # 2. pyzbar (agar mavjud bo‘lsa)
    if PYZBAR_AVAILABLE:
        enhanced = _enhance_for_qr(image)
        decoded_objects = pyzbar_decode(enhanced)

        try:
            # Rasmni grayscale ga o‘tkazamiz (pyzbar uchun)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # pyzbar decode
            # decoded_objects = pyzbar_decode(gray)
            for obj in decoded_objects:
                if obj.type == 'QRCODE':
                    data = obj.data.decode('utf-8')
                    if data:
                        return data
        except Exception as e:
            logger.debug("pyzbar decode xatosi: %s", e)

    # 3. Agar rasm rangli bo‘lsa va pyzbar ishlamasa, boshqa yondashuvlar qo‘shish mumkin
    # Masalan: PIL bilan o‘qish, lekin hozircha yetarli

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

    MUHIM: marker markazi endi cv2.moments() (konturning og'irlik
    markazi) orqali SUBPIXEL aniqlikda hisoblanadi -- oldingi
    cv2.boundingRect() asosidagi usul (chap-yuqori burchak + yarim
    o'lcham) piksel darajasida yaxlitlanadi, bu esa keyingi
    perspective-correction'da butun sahifa bo'ylab proporsional
    xatoga aylanib ketadi.

    Qaytaradi: {"tl": (x, y), "tr": (x, y), "bl": (x, y), "br": (x, y)}
    Topilmagan burchaklar lug'atda bo'lmaydi.
    """

    gray = to_gray(image)
    h, w = gray.shape

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # MUHIM: global (Otsu) threshold emas, LOKAL (adaptive) threshold
    # ishlatiladi. Fotoda qog'ozdan tashqarida (stol, soya va h.k.)
    # turlicha yorug'lik/rang bo'lishi mumkin -- global threshold bunday
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
    # qat'iy nazar barcha konturlarni qaytaradi -- filtrlash
    # (o'lcham/nisbat/burchakka yaqinlik) haqiqiy markerni baribir
    # aniq topib beradi.
    contours, _ = cv2.findContours(
        threshold,
        cv2.RETR_LIST,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    image_area = float(w * h)

    # Marker chizilgan (MARKER_SIZE_MM) / sahifa (210mm) nisbati
    # asosida kutilayotgan yuza ulushi (juda keng oraliqda, chunki
    # foto burchaklarida qog'ozdan tashqari fon ham bo'lishi mumkin)
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
        contour_area = cv2.contourArea(contour)
        fill_ratio = contour_area / float(area + 1e-6)

        if fill_ratio < 0.55:
            continue

        # SUBPIXEL MARKAZ: bounding-box o'rtasi o'rniga konturning
        # og'irlik markazi (image moments). m00 == 0 bo'lsa (nol yuzali
        # kontur) -- xavfsiz o'tkazib yuboriladi.
        M = cv2.moments(contour)
        if M["m00"] == 0:
            continue
        center = (M["m10"] / M["m00"], M["m01"] / M["m00"])

        quadrant = _quadrant_of(center, w, h)

        # Mos burchakka (rasmning haqiqiy burchak nuqtasiga)
        # bo'lgan masofa -- bu bilan markerni QR yoki boshqa
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
# TIMING TRACK -- HAQIQIY QATOR Y-MARKAZINI TOPISH
# ============================================================

def find_timing_marks(
    binary: np.ndarray,
    column_left_px: float,
    header_bottom_px: float,
    row_h_px: float,
    max_rows: int,
    offset_px: float,
    mark_size_px: float,
) -> Optional[Dict[int, float]]:
    """
    Ustunning chap chetidagi timing track'da (har bir qator uchun
    kichik to'ldirilgan kvadrat, answer_sheet_generator.py chizgan)
    HAQIQIY y-markazlarini topadi.

    Bu -- reader'ning "aniqlikning yuragi": qator y-pozitsiyasini
    arifmetik formula (`header_bottom + i * row_h`) bilan HISOBLASH
    o'rniga, siyohning o'zidan o'qiydi. Shu bilan global
    perspective-correction xatosi (marker markazidagi bir necha
    piksellik noaniqlik) pastki qatorlarda to'planib ketishining
    oldi olinadi.

    Muvaffaqiyatli bo'lsa: {row_index: y_px, ...} (0-indeksli) qaytaradi.
    Aniq `max_rows` ta belgi topilmasa (masalan eski, timing-track'siz
    shablon yoki juda shovqinli foto) -- None qaytaradi, chaqiruvchi
    arifmetik formulaga xavfsiz qaytadi (backward-compatible).
    """

    strip_half_w = int(mark_size_px * 1.8)
    x1 = max(0, int(column_left_px + offset_px - strip_half_w))
    x2 = int(column_left_px + offset_px + strip_half_w)

    y1 = max(0, int(header_bottom_px - row_h_px))
    y2 = int(header_bottom_px + row_h_px * (max_rows + 1))

    if x2 <= x1 or y2 <= y1 or y2 > binary.shape[0] or x2 > binary.shape[1]:
        return None

    strip = binary[y1:y2, x1:x2]

    contours, _ = cv2.findContours(strip, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = (mark_size_px * 0.45) ** 2
    max_area = (mark_size_px * 3.0) ** 2

    blob_centers_y = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        M = cv2.moments(cnt)
        if M["m00"] == 0:
            continue
        cy = M["m01"] / M["m00"] + y1
        blob_centers_y.append(cy)

    if len(blob_centers_y) != max_rows:
        # Ishonchsiz -- fallback arifmetikaga (chaqiruvchi tomonida)
        return None

    blob_centers_y.sort()

    return {i: cy for i, cy in enumerate(blob_centers_y)}


# ============================================================
# BITTA QATORDAGI BUBBLE MARKAZLARINI LOKAL RAVISHDA ANIQLASH
# ============================================================

def refine_bubble_centers_in_row(
    gray: np.ndarray,
    y_center_px: int,
    predicted_xs_px: List[int],
    radius_px: float,
) -> List[Tuple[int, int]]:
    """
    Bitta qatordagi 4 ta bubble (A/B/C/D) uchun formuladan olingan
    x-koordinatalarni HAQIQIY doira markazlariga moslashtiradi
    (cv2.HoughCircles orqali).

    Bu -- timing track qatorning y-pozitsiyasini to'g'irlagandan
    keyin, x o'qi bo'yicha ham qog'ozning kichik cho'zilishi/siljishi
    (yoki qoldiq perspective xatosi) hisobga olinishi uchun.

    Agar biror sababga ko'ra doira topilmasa (masalan juda xira foto
    yoki bubble haddan tashqari to'ldirilgan/qoralangan bo'lsa),
    formula bergan x-koordinata O'ZGARISHSIZ qaytariladi -- shuning
    uchun bu funksiya natijani hech qachon yomonlashtirmaydi, faqat
    yaxshilashi yoki neytral qolishi mumkin.
    """

    pad = int(radius_px * 1.4)
    x1 = max(0, min(predicted_xs_px) - pad)
    x2 = max(predicted_xs_px) + pad
    y1 = max(0, y_center_px - pad)
    y2 = y_center_px + pad

    fallback = [(px, y_center_px) for px in predicted_xs_px]

    if y2 > gray.shape[0] or x2 > gray.shape[1] or x2 <= x1 or y2 <= y1:
        return fallback

    strip = gray[y1:y2, x1:x2]

    if strip.size == 0:
        return fallback

    blurred = cv2.GaussianBlur(strip, (3, 3), 0)

    try:
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.0,
            minDist=max(radius_px * 1.4, 1),
            param1=50,
            param2=18,
            minRadius=int(radius_px * 0.65),
            maxRadius=int(radius_px * 1.35),
        )
    except cv2.error:
        return fallback

    if circles is None:
        return fallback

    detected = [(float(cx) + x1, float(cy) + y1) for cx, cy, r in circles[0]]

    # Har bir formula-x uchun eng yaqin (moslik chegarasidan ichkarida
    # bo'lgan) detected doirani tanlaymiz. Bir doira faqat bitta
    # harfga moslashtiriladi (used to'plami orqali).
    match_tolerance_px = radius_px * 0.8
    used_indices = set()
    refined: List[Tuple[int, int]] = []

    for px in predicted_xs_px:
        best_idx = None
        best_dist = match_tolerance_px
        for idx, (dx, dy) in enumerate(detected):
            if idx in used_indices:
                continue
            dist = abs(dx - px)
            if dist < best_dist:
                best_idx = idx
                best_dist = dist
        if best_idx is not None:
            used_indices.add(best_idx)
            dx, dy = detected[best_idx]
            refined.append((int(round(dx)), int(round(dy))))
        else:
            refined.append((px, y_center_px))

    return refined


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
    `binary` -- make_binary() natijasi (ink = 255, qog'oz = 0).

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
        EMAS -- qog'oz g'adir-budurligi, soya, JPEG siqilishi kabi
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
        centers_px=list(centers_px),
    )

def find_variant_timing_marks(binary: np.ndarray) -> Optional[List[float]]:
    """
    TEST VARIANTI qatoridagi 4 ta timing mark (har bir bubble ostida)
    ning HAQIQIY x-markazlarini topadi -- find_timing_marks() bilan bir
    xil mantiq, lekin vertikal ustun o'rniga bitta GORIZONTAL qator uchun.

    Muvaffaqiyatli bo'lsa: chapdan o'ngga saralangan 4 ta x_px qaytaradi.
    Aniq 4 ta belgi topilmasa -- None (chaqiruvchi arifmetik formulaga
    xavfsiz qaytadi).
    """
    predicted_y_px = (VARIANT_BUBBLE_Y_MM + VARIANT_TIMING_MARK_OFFSET_MM) * PX_PER_MM
    mark_size_px = VARIANT_TIMING_MARK_SIZE_MM * PX_PER_MM

    x1 = int((min(VARIANT_BUBBLE_XS_MM) - 5) * PX_PER_MM)
    x2 = int((max(VARIANT_BUBBLE_XS_MM) + 5) * PX_PER_MM)
    y1 = max(0, int(predicted_y_px - mark_size_px * 2))
    y2 = int(predicted_y_px + mark_size_px * 2)

    if x2 <= x1 or y2 <= y1 or y2 > binary.shape[0] or x2 > binary.shape[1]:
        return None

    strip = binary[y1:y2, x1:x2]
    contours, _ = cv2.findContours(strip, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = (mark_size_px * 0.45) ** 2
    max_area = (mark_size_px * 3.0) ** 2

    centers_x = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        M = cv2.moments(cnt)
        if M["m00"] == 0:
            continue
        centers_x.append(M["m10"] / M["m00"] + x1)

    if len(centers_x) != MAX_PAPER_VARIANTS:
        return None

    centers_x.sort()
    return centers_x


@dataclass
class VariantDetectionResult:
    variant_number: Optional[int]   # 1..4, aniqlangan bo'lsa
    status: str                     # "blank" | "marked" | "uncertain"
    options: List[OptionResult]


def detect_paper_variant(gray: np.ndarray, binary: np.ndarray) -> VariantDetectionResult:
    """
    TEST VARIANTI qatoridagi 4 ta bubble'dan qaysi biri belgilanganini
    aniqlaydi. Talaba variant belgilamagan (yoki bu imtihonda variant
    umuman ishlatilmagan) bo'lsa -- status="blank", variant_number=None
    qaytadi. Bu XATO EMAS: chaqiruvchi (omr_service.py) tomonida
    ExamStudent.paper_variant_number None bo'lsa, solishtirish umuman
    o'tkazib yuboriladi.
    """
    radius_px = VARIANT_BUBBLE_RADIUS_MM * PX_PER_MM

    timing_xs = find_variant_timing_marks(binary)
    if timing_xs is not None:
        predicted_xs_px = [int(round(cx)) for cx in timing_xs]
    else:
        predicted_xs_px = [int(round(cx * PX_PER_MM)) for cx in VARIANT_BUBBLE_XS_MM]

    y_center_px = int(round(VARIANT_BUBBLE_Y_MM * PX_PER_MM))
    centers = refine_bubble_centers_in_row(gray, y_center_px, predicted_xs_px, radius_px)

    options: List[OptionResult] = []
    for label, (cx, cy) in zip(["1", "2", "3", "4"], centers):
        options.append(OptionResult(letter=label, fill_percentage=get_fill_percentage(binary, cx, cy, radius_px)))

    ranked = sorted(options, key=lambda o: o.fill_percentage, reverse=True)
    best, second = ranked[0], ranked[1]
    margin = best.fill_percentage - second.fill_percentage

    blank_threshold, marked_threshold, min_margin = 15.0, 32.0, 8.0

    if best.fill_percentage < blank_threshold:
        return VariantDetectionResult(None, "blank", options)
    if margin < min_margin:
        if best.fill_percentage < marked_threshold:
            return VariantDetectionResult(None, "blank", options)
        return VariantDetectionResult(int(best.letter), "uncertain", options)
    status = "marked" if best.fill_percentage >= marked_threshold else "uncertain"
    return VariantDetectionResult(int(best.letter), status, options)

# ============================================================
# BUTUN JAVOB VARAQASINI O'QISH
# ============================================================

def _question_centers_px(question_number: int) -> List[Tuple[int, int]]:
    """
    FALLBACK: berilgan savol raqami uchun A/B/C/D bubble markazlarini
    SOF ARIFMETIK formula bilan (piksel, TARGET_DPI asosida) qaytaradi.

    Bu funksiya endi asosiy yo'l EMAS -- detect_answer_sheet() avval
    timing track + Hough orqali aniq koordinata topishga harakat
    qiladi. Bu funksiya faqat: (a) timing track topilmagan holatlarda
    ustun ichidagi boshlang'ich taxmin sifatida va (b) debug overlay
    uchun (agar QuestionResult.centers_px yo'q bo'lsa) ishlatiladi.
    """

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


def _column_index_for_question(question_number: int) -> int:
    for column_index, (start, end) in enumerate(QUESTION_GROUPS):
        if start <= question_number <= end:
            return column_index
    raise ValueError(f"Noma'lum savol raqami: {question_number}")


def _detect_column_questions(
    gray: np.ndarray,
    binary: np.ndarray,
    column_index: int,
    radius_px: float,
) -> List[QuestionResult]:
    """
    Bitta ustundagi (30 ta savol) barcha savollarni o'qiydi.

    Qadamlar:
      1. Timing track'ni qidiradi -- topilsa, har bir qatorning
         HAQIQIY y-markazi shundan olinadi.
      2. Topilmasa (eski shablon / shovqin) -- arifmetik y ishlatiladi.
      3. Har bir qatorda, x-koordinatalar Hough orqali lokal
         ravishda aniqlanadi (topilmasa -- formula x ishlatiladi).
    """

    start, end = QUESTION_GROUPS[column_index]
    column_left_mm = COLUMN_LEFT_MM[column_index]

    column_left_px = column_left_mm * PX_PER_MM
    header_bottom_px = (ANSWER_TOP_MM + HEADER_H_MM) * PX_PER_MM
    row_h_px = ROW_H_MM * PX_PER_MM
    offset_px = TIMING_MARK_OFFSET_MM * PX_PER_MM
    mark_size_px = TIMING_MARK_SIZE_MM * PX_PER_MM

    timing_marks = find_timing_marks(
        binary,
        column_left_px=column_left_px,
        header_bottom_px=header_bottom_px,
        row_h_px=row_h_px,
        max_rows=MAX_ROWS,
        offset_px=offset_px,
        mark_size_px=mark_size_px,
    )

    results: List[QuestionResult] = []

    for row_index in range(MAX_ROWS):

        question_number = start + row_index

        if question_number > end:
            continue

        if timing_marks is not None:
            y_center_px = int(round(timing_marks[row_index]))
        else:
            # Fallback: sof arifmetika (eski xatti-harakat)
            center_y_mm = (
                ANSWER_TOP_MM
                + HEADER_H_MM
                + row_index * ROW_H_MM
                + ROW_H_MM / 2
            )
            y_center_px = int(round(center_y_mm * PX_PER_MM))

        predicted_xs_px = [
            int(round((column_left_mm + offset) * PX_PER_MM))
            for offset in ANSWER_OFFSETS_MM
        ]

        centers = refine_bubble_centers_in_row(
            gray,
            y_center_px,
            predicted_xs_px,
            radius_px,
        )

        result = detect_question(
            binary,
            question_number,
            centers,
            radius_px,
        )

        results.append(result)

    return results


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
            "Rasm tekislanmasdan (asl holida) ishlanadi -- "
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

    quality_warnings = assess_image_quality(gray)
    if len(markers) < 4:
        quality_warnings.append(
            "4 ta registratsiya markeridan hammasi topilmadi -- natija "
            "noaniq bo'lishi mumkin."
        )
    for w in quality_warnings:
        print("SIFAT OGOHLANTIRISHI:", w)

    radius_px = BUBBLE_RADIUS_MM * PX_PER_MM
    results: List[QuestionResult] = []
    for column_index in range(len(QUESTION_GROUPS)):
        results.extend(_detect_column_questions(gray, binary, column_index, radius_px))

    variant_result = detect_paper_variant(gray, binary)   # YANGI

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
        "quality_warnings": quality_warnings,
        "questions": results,
        "detected_paper_variant": variant_result.variant_number,   # YANGI
        "paper_variant_status": variant_result.status,             # YANGI
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
    if report.get("quality_warnings"):
        print("OGOHLANTIRISHLAR:")
        for w in report["quality_warnings"]:
            print(f"  - {w}")
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
        Sariq   = noaniq (uncertain) -- qo'lda tekshirish kerak
        Kulrang = bo'sh (blank)

    MUHIM: endi HAR BIR natijaning o'zida saqlangan haqiqiy
    (`result.centers_px` -- timing track + Hough orqali topilgan)
    koordinatalar ishlatiladi, sof arifmetik formula emas. Shu
    sababli debug rasm reader qayerni "ko'rgani"ni AYNAN ko'rsatadi.

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

        centers = result.centers_px or _question_centers_px(result.question)

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
    image_path = "murakkab22.jpg"
    report = detect_answer_sheet(image_path)

    print_report(report)

    debug_path = draw_debug_overlay(report, "output/debug_overlay.jpg")

    print(f"\nDebug rasm saqlandi: {debug_path}")