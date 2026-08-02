# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from weasyprint import HTML
from app.utils.latex_render import render_latex_in_html


def _question_html(position: int, q: dict) -> str:
    tartib = q.get("tartib") or q.get("T/r") or position
    savol = render_latex_in_html(q.get("savol_html", ""))
    jadval = render_latex_in_html(q.get("jadval_html", ""))
    rasm = f'<img class="question-image" src="{q["savol_rasm_url"]}">' if q.get("savol_rasm_url") else ""

    options_html = ""

    # 1. USUL: variant_a_html, variant_b_html, ...
    has_variant_keys = any(q.get(f"variant_{letter.lower()}_html") for letter in ["A", "B", "C", "D"])
    if has_variant_keys:
        for letter in ["A", "B", "C", "D"]:
            opt_html = render_latex_in_html(q.get(f"variant_{letter.lower()}_html", ""))
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

    # 3. USUL: to'g'ridan-to'g'ri A, B, C, D kalitlari (agar variant kalitlari mavjud bo'lmasa)
    if not options_html:
        for letter in ["A", "B", "C", "D"]:
            opt_html = q.get(letter) or q.get(f"variant_{letter}", "")
            if opt_html:
                options_html += (
                    f'<div class="option"><span class="option-letter">{letter})</span> '
                    f'<span class="option-text">{render_latex_in_html(str(opt_html))}</span></div>'
                )

    return f"""
    <div class="question" style="page-break-inside: avoid;">
        <div class="question-head">
            <span class="q-number">{tartib}.</span>
            <div class="q-body">{savol}{rasm}{jadval}</div>
        </div>
        <div class="options">{options_html}</div>
    </div>
    """


_PAGE_CSS = """
@page {
    size: A4;
    margin: 20mm 18mm 22mm 18mm;
    @bottom-center { content: counter(page) "-bet"; font-size: 8pt; color: #666; }
}
body { font-family: "DejaVu Sans", sans-serif; font-size: 10.5pt; color: #111; line-height: 1.4; }
.cover { text-align: center; }
.cover .brand { font-size: 8pt; color: #666; letter-spacing: 1px; }
.cover h1 { font-size: 18pt; margin: 6mm 0; }
.cover .exam-id { font-size: 8pt; color: #666; }
.student-box { border: 1px solid #999; border-radius: 4px; padding: 6mm; margin: 10mm auto; width: 120mm; }
.student-box .label { font-size: 6.5pt; color: #666; font-weight: bold; }
.student-box .name { font-size: 12pt; font-weight: bold; margin: 2mm 0; }
.digit-row { display: flex; justify-content: center; gap: 2mm; margin: 6mm 0; }
.variant-box { margin: 5mm auto; width: 50mm; border: 1.5px solid #333; border-radius: 4px; padding: 3mm; }
.variant-box .variant-label { font-size: 7pt; color: #666; font-weight: bold; }
.variant-box .variant-number { font-size: 20pt; font-weight: bold; margin-top: 1mm; }
.digit-box { border: 1px solid #333; border-radius: 2px; width: 8mm; height: 11mm;
             display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 11pt; }
.instructions { border: 1px solid #999; border-radius: 4px; padding: 6mm; margin: 10mm auto;
                width: 160mm; font-size: 8pt; text-align: left; color: #333; }
.instructions li { margin-bottom: 2mm; }
.subject-header { text-align: center; font-weight: bold; font-size: 12pt; border-bottom: 1px solid #999;
                   padding-bottom: 2mm; margin-bottom: 6mm; }
.question {
    margin-bottom: 5mm;
    page-break-inside: avoid;
}
.question-head { display: flex; gap: 2mm; }
.q-number { font-weight: bold; min-width: 6mm; }
.options { margin-left: 8mm; margin-top: 1.5mm; }
.option { margin-bottom: 1mm; }
.option-letter { font-weight: bold; }
img.latex-inline { vertical-align: middle; height: 3.4mm; }
img.question-image {
    display: block;
    max-width: 120mm;
    max-height: 90mm;
    width: auto;
    height: auto;
    margin: 2mm auto;
    border-radius: 4px;
}
.latex-block { text-align: center; margin: 2mm 0; }
.latex-block-img { max-width: 100%; }
/* Jadval uslublari */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 2mm 0;
    font-size: 9pt;
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
    variant_label: str | None = None,
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
    for fan, qs in pages:
        questions_html = "".join(
            _question_html(q.get("tartib", q.get("T/r", i + 1)), q)
            for i, q in enumerate(qs)
        )
        body_pages.append(
            f'<div class="subject-header">{fan}</div>{questions_html}<div style="page-break-after: always;"></div>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{_PAGE_CSS}</style></head>
<body>{cover_html}{''.join(body_pages)}</body></html>"""


def render_booklet_pdf(
    student: dict, exam_id: str, booklet_id: str,
    rendered_questions: list[dict], output_path: str, brand_name: str = "BRAND NAME",
    variant_label: str | None = None,
) -> str:
    html = build_booklet_html(
        student, exam_id, booklet_id, rendered_questions,
        brand_name=brand_name, variant_label=variant_label,
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(output_path)
    return output_path