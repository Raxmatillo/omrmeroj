# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from weasyprint import HTML
from app.utils.latex_render import render_latex_in_html
import app.utils as _utils_pkg

# MUHIM: bu fayl (booklet_html_generator.py) "omr/" papkasida, lekin
# katex_assets/ esa "utils/" papkasida joylashgan -- shuning uchun
# Path(__file__).parent ISHLATILMAYDI (u "omr/" ni bergan bo'lardi).
# O'rniga app.utils modulining HAQIQIY joylashuvidan foydalanamiz --
# bu fayllar kelajakda boshqa papkalarga ko'chirilsa ham to'g'ri
# ishlashda davom etadi.

_UTILS_DIR = Path(_utils_pkg.__file__).parent
_KATEX_ASSETS_DIR = _UTILS_DIR / "katex_assets"   # <-- YANGI
_KATEX_CSS_PATH = _KATEX_ASSETS_DIR / "katex.min.css"
_katex_css_cache: str | None = None

def _get_katex_css() -> str:
    """katex.min.css matnini bir marta o'qib, keshda saqlaydi -- har
    bir kitobcha generatsiyasida qayta diskdan o'qimaslik uchun."""
    global _katex_css_cache
    if _katex_css_cache is None:
        try:
            _katex_css_cache = _KATEX_CSS_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            # KaTeX CSS topilmasa, formula HTML'i chiqadi-yu, lekin
            # shriftsiz/formatsiz -- shovqin ko'tarish o'rniga bo'sh
            # qoldiramiz, lekin bu holat sukut saqlamasligi kerak --
            # shuning uchun ishlab chiquvchi buni loglardan bilishi
            # uchun ogohlantirish chiqaramiz.
            import logging
            logging.getLogger(__name__).error(
                f"KaTeX CSS topilmadi: {_KATEX_CSS_PATH} -- formulalar "
                f"noto'g'ri ko'rinishi mumkin!"
            )
            _katex_css_cache = ""
    return _katex_css_cache


def _format_ball_label(qs: list[dict]) -> str:
    """Berilgan savollar blokidagi ball(lar)ni '1.1 ball' yoki
    aralash bo'lsa '1-2 ball' ko'rinishida formatlaydi."""
    balls = []
    for q in qs:
        b = q.get("ball")
        if b is None:
            continue
        try:
            balls.append(float(b))
        except (TypeError, ValueError):
            continue

    if not balls:
        return ""

    distinct = sorted(set(balls))
    if len(distinct) == 1:
        return f"{distinct[0]:g} ball"
    return f"{distinct[0]:g}-{distinct[-1]:g} ball"


def _question_html(position: int, q: dict) -> str:
    savol = render_latex_in_html(q.get("savol_html", ""))
    jadval = render_latex_in_html(q.get("jadval_html", ""))

    style = q.get("savol_rasm_style", "medium")
    size_classes = {
        "small": "max-width: 60mm; max-height: 45mm;",
        "medium": "max-width: 100mm; max-height: 75mm;",
        "large": "max-width: 130mm; max-height: 100mm;",
        "original": "max-width: 100%; height: auto;",
    }
    img_style = size_classes.get(style, size_classes["medium"])
    rasm = (
        f'<div class="question-image-wrap"><img class="question-image" '
        f'src="{q["savol_rasm_url"]}" style="{img_style}" /></div>'
        if q.get("savol_rasm_url") else ""
    )

    options_html = ""

    # 1. USUL: variant_a_html, variant_b_html, ...
    variant_keys = ["variant_a_html", "variant_b_html", "variant_c_html", "variant_d_html"]
    has_variant_keys = any(k in q for k in variant_keys)
    if has_variant_keys:
        for letter, key in zip(["A", "B", "C", "D"], variant_keys):
            opt_html = render_latex_in_html(q.get(key, ""))
            if opt_html.strip():
                options_html += (
                    f'<div class="option"><span class="option-letter">{letter})</span> '
                    f'<span class="option-text">{opt_html}</span></div>'
                )

    # 2. USUL: eski `options` kaliti (agar yuqorida bo'sh bo'lsa)
    if not options_html and "options" in q:
        for opt in q["options"]:
            opt_html = render_latex_in_html(opt.get("html", ""))
            if opt_html.strip():
                options_html += (
                    f'<div class="option"><span class="option-letter">{opt["letter"]})</span> '
                    f'<span class="option-text">{opt_html}</span></div>'
                )

    # 3. USUL: to'g'ridan-to'g'ri A, B, C, D kalitlari
    if not options_html:
        for letter in ["A", "B", "C", "D"]:
            opt_html = q.get(letter) or q.get(f"variant_{letter}", "")
            if opt_html:
                options_html += (
                    f'<div class="option"><span class="option-letter">{letter})</span> '
                    f'<span class="option-text">{render_latex_in_html(str(opt_html))}</span></div>'
                )

    return f"""
    <div class="question">
        <div class="question-head">
            <span class="q-number">{position}.</span>
            <div class="q-body">{savol}{rasm}{jadval}</div>
        </div>
        <div class="options">{options_html}</div>
    </div>
    """


_PAGE_CSS = """
@page {
    size: A4;
    margin: 16mm 14mm 18mm 14mm;
    @bottom-center { content: counter(page) "-bet"; font-size: 8pt; color: #666; }
}
body { font-family: "DejaVu Sans", sans-serif; font-size: 12pt; color: #111; line-height: 1.5; }
.cover { text-align: center; }
.cover .brand { font-size: 10pt; color: #666; letter-spacing: 1px; }
.cover h1 { font-size: 22pt; margin: 6mm 0; }
.cover .exam-id { font-size: 9pt; color: #666; }
.student-box { border: 1px solid #999; border-radius: 4px; padding: 6mm; margin: 8mm auto; width: 120mm; }
.student-box .label { font-size: 9pt; color: #666; font-weight: bold; }
.student-box .name { font-size: 16pt; font-weight: bold; margin: 2mm 0; }
.digit-row { display: flex; justify-content: center; gap: 2mm; margin: 6mm 0; }
.variant-box { margin: 5mm auto; width: 50mm; border: 1.5px solid #333; border-radius: 4px; padding: 3mm; }
.variant-box .variant-label { font-size: 8pt; color: #666; font-weight: bold; }
.variant-box .variant-number { font-size: 24pt; font-weight: bold; margin-top: 1mm; }
.digit-box { border: 1px solid #333; border-radius: 2px; width: 8mm; height: 11mm;
             display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 11pt; }
.instructions { border: 1px solid #999; border-radius: 4px; padding: 6mm; margin: 8mm auto;
                width: 150mm; font-size: 10pt; text-align: left; color: #333; }
.instructions li { margin-bottom: 2mm; }

/* ------------------------------------------------------------------
   SAHIFALANISH (page-break / fragmentation) qoidalari.

   MUHIM: bitta joyga "page-break-inside: avoid" qo'yish YETARLI EMAS --
   agar savol (rasm + matn + 4 variant) BUTUNLAY bir sahifadan baland
   bo'lib qolsa, WeasyPrint baribir majburan biror joydan bo'ladi va
   bo'linish nuqtasi tasodifiy (masalan variant matni o'rtasidan)
   tushib qolishi mumkin. Shu sababli himoya HAR DARAJAGA qo'yiladi:
   avval butun savol bloki (mumkin bo'lsa umuman bo'linmasin), keyin
   sarlavha+rasm qismi, keyin variantlar ro'yxati, keyin har bir
   variant alohida -- shunda majburan bo'linish kerak bo'lsa ham,
   ENG YOMONI ikki variant ORASIDAN bo'linadi, biror variantning
   ICHIDAN emas.

   `break-inside` -- zamonaviy CSS Fragmentation nomi, `page-break-inside`
   -- eski nom (ba'zi renderlarda faqat biri tan olinishi mumkin edi).
   Ikkalasi ham qo'yilgan -- WeasyPrint ikkalasini ham qo'llab-quvvatlaydi,
   ortiqcha yozish zarar qilmaydi.
------------------------------------------------------------------- */
.subject-header {
    text-align: center; font-weight: bold; font-size: 14pt; border-bottom: 1px solid #999;
    padding-bottom: 2mm; margin-bottom: 6mm;
    break-after: avoid-page; page-break-after: avoid;
}
.subject-header .ball-label {
    font-weight: normal; font-size: 10pt; color: #555;
}
.question {
    margin-bottom: 6mm;
    break-inside: avoid-page;
    page-break-inside: avoid;
}
.question-head {
    display: flex; gap: 2mm;
    break-inside: avoid-page;
    page-break-inside: avoid;
}
.q-number { font-weight: bold; min-width: 6mm; }
.q-body { flex: 1 1 auto; min-width: 0; }
.q-body img:not(.question-image) {
    display: inline;
    vertical-align: middle;
}

.option {
    display: flex;
    align-items: baseline;   /* harf va formula bir chiziqda tursin */
    gap: 1.5mm;
    margin-bottom: 1.2mm;
    break-inside: avoid-page;
    page-break-inside: avoid;
}
.option-letter { font-weight: bold; flex-shrink: 0; }
.option-text {
    flex: 1 1 auto;
    min-width: 0;
}

/* Variant matni ichida "block" formula (a/b kabi $$..$$/mathBlock)
   uchrasa ham, endi div yangi qatorga tushmaydi -- harf bilan
   yonma-yon, o'rtacha (vertical-align: middle) tekislanadi. */
.option-text .latex-block {
    display: inline-block;
    margin: 0;
    vertical-align: middle;
}

.latex-inline img {
    vertical-align: -0.15em;
}

.latex-inline svg {
    height:1.2em;
    width:auto;
    vertical-align:-0.15em;
}
.latex-block svg{
    max-width:100%;
    height:auto;
}
.question-image-wrap {
    display: block;
    width: 100%;
    text-align: center;
    margin: 2mm 0;
    break-inside: avoid-page;
    page-break-inside: avoid;
}
img.question-image {
    display: inline-block;
    max-width: 120mm;
    max-height: 80mm;
    width: auto;
    height: auto;
    object-fit: contain;
    margin: 0 auto;
}
img.question-image-small { max-width: 60mm; max-height: 45mm; }
img.question-image-medium { max-width: 100mm; max-height: 75mm; }
img.question-image-large { max-width: 130mm; max-height: 100mm; }
img.question-image-original { max-width: 100%; height: auto; }

table {
    border-collapse: collapse;
    width: 100%;
    margin: 2mm 0;
    font-size: 10pt;
    break-inside: avoid-page;
    page-break-inside: avoid;
}
th, td {
    border: 0.5pt solid #333;
    padding: 1mm 2mm;
    text-align: left;
    vertical-align: middle;
}
th {
    background: #f0f0f0;
    font-weight: bold;
}
"""


def build_booklet_html(
    student: dict, exam_id: str, booklet_id: str,
    rendered_questions: list[dict], brand_name: str = "BRAND NAME",
    variant_label: str | None = None, exam_name: str | None = None
) -> str:
    fanlar_str = ", ".join(sorted({q["fan"] for q in rendered_questions}))

    variant_html = (
        f'<div style="margin-top:2mm;font-size:8pt;font-weight:bold;">Variant: {variant_label}</div>'
        if variant_label else ""
    )

    cover_html = f"""
    <div class="cover">
        <div class="brand">{brand_name}</div>
        <h1>SAVOLLAR KITOBCHASI</h1>
        <div class="exam-id">Imtihon ID: {exam_id}</div>
        <div class="student-box">
            <div class="label">TALABA</div>
            <div class="name">{student['full_name']}</div>
            <div>{student.get('group_name', '')}</div>
            <div style="margin-top:3mm;font-size:7.5pt;color:#666;">Fanlar: {fanlar_str}</div>
            {variant_html}
        </div>
        <div class="instructions">
            <b>KO'RSATMA</b>
            <ol>
                <li>Har bir savolga faqat bitta javob belgilang.</li>
                <li>Javoblarni ushbu kitobchaga emas, alohida javoblar varag'iga bo'yab belgilang.</li>
                <li>Yuqoridagi 7 xonali savol ID ni javoblar varag'ida ham bo'yab belgilang.</li>
                <li>Kitobchani boshqa talabaga bermang -- savollar tartibi va variantlar individual.</li>
                <li>Vaqt tugagach kitobcha va javoblar varag'ini o'qituvchiga topshiring.</li>
            </ol>
        </div>
    </div>
    <div style="page-break-after: always;"></div>
    """

    pages: list[tuple[str, list[dict]]] = []
    current_fan = None
    current_block: list[dict] = []
    for q in rendered_questions:
        if q["fan"] != current_fan:
            if current_block:
                pages.append((current_fan, current_block))
            current_fan = q["fan"]
            current_block = []
        current_block.append(q)
    if current_block:
        pages.append((current_fan, current_block))

    body_pages = []
    global_index = 1

    for fan, qs in pages:
        ball_label = _format_ball_label(qs)
        ball_html = f' <span class="ball-label">({ball_label})</span>' if ball_label else ""
        fan_header = f'<div class="subject-header">{fan}{ball_html}</div>'
        questions_html = ""
        for q in qs:
            questions_html += _question_html(global_index, q)
            global_index += 1
        body_pages.append(
            fan_header + questions_html + '<div style="page-break-after: always;"></div>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>{_get_katex_css()}</style>
<style>{_PAGE_CSS}</style>
</head>
<body>{cover_html}{''.join(body_pages)}</body></html>"""


def render_booklet_pdf(
    student: dict, exam_id: str, booklet_id: str,
    rendered_questions: list[dict], output_path: str, brand_name: str = "BRAND NAME",
    variant_label: str | None = None, exam_name: str | None = None
) -> str:
    html = build_booklet_html(
        student, exam_id, booklet_id, rendered_questions,
        brand_name=brand_name, variant_label=variant_label, exam_name=exam_name
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # MUHIM: base_url ham "omr/" emas, "utils/" papkasiga ishora
    # qilishi kerak -- chunki katex.min.css ichidagi
    # @font-face { src: url(fonts/...) } shu papkaga nisbatan
    # hisoblanadi (katex_assets/fonts/... o'sha yerda joylashgan).
    # base_url = _KATEX_ASSETS_DIR.as_uri()   # <-- o'zgardi (avval _UTILS_DIR edi)\
    base_url = _KATEX_ASSETS_DIR.as_uri() + "/"   
    print(f"Rendering booklet PDF to {output_path} (base_url={base_url})...")
    HTML(string=html, base_url=base_url).write_pdf(output_path)
    return output_path