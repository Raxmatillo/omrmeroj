# -*- coding: utf-8 -*-
"""
WeasyPrint asosidagi savollar kitobi (question booklet) generatori.

Eski `generate_question_booklet.py` (reportlab, plain-text, Excel'dan
standalone ishga tushiriladigan demo skript) ORQASIGA QOLDIRILMAYDI --
u hamon app/utils/excel_import.py orqali keladigan Excel-based import
uchun ishlatilaveradi. Bu YANGI modul esa DB'dagi savol_html/HTML
kontentni (TipTap admin panelidan keladigan, LaTeX $...$ bo'lishi mumkin
bo'lgan) to'g'ridan-to'g'ri render qiladi -- shu sababli kelajakda admin
panelidan savolni tahrirlasangiz, PDF navbatdagi generatsiyada avtomatik
yangilanadi (PDF statik fayl emas, har safar shu HTML'dan qayta
generatsiya qilinadi).
"""
from __future__ import annotations

from pathlib import Path

from weasyprint import HTML

from app.utils.latex_render import render_latex_in_html


def _digit_boxes_html(digits: str) -> str:
    cells = "".join(f'<div class="digit-box">{d}</div>' for d in digits)
    return f'<div class="digit-row">{cells}</div>'


def _question_html(position: int, q: dict) -> str:
    savol = render_latex_in_html(q["savol_html"])
    jadval = render_latex_in_html(q.get("jadval_html"))
    rasm = f'<img class="question-image" src="{q["savol_rasm_url"]}">' if q.get("savol_rasm_url") else ""

    options_html = ""
    for opt in q["options"]:
        opt_html = render_latex_in_html(opt["html"])
        options_html += (
            f'<div class="option"><span class="option-letter">{opt["letter"]})</span> '
            f'<span class="option-text">{opt_html}</span></div>'
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
    margin: 20mm 18mm 22mm 18mm;
    @bottom-center { content: counter(page) "-bet"; font-size: 8pt; color: #666; }
}
body { font-family: "DejaVu Sans", sans-serif; font-size: 10.5pt; color: #111; }
.cover { text-align: center; }
.cover .brand { font-size: 8pt; color: #666; letter-spacing: 1px; }
.cover h1 { font-size: 18pt; margin: 6mm 0; }
.cover .exam-id { font-size: 8pt; color: #666; }
.student-box { border: 1px solid #999; border-radius: 4px; padding: 6mm; margin: 10mm auto; width: 120mm; }
.student-box .label { font-size: 6.5pt; color: #666; font-weight: bold; }
.student-box .name { font-size: 12pt; font-weight: bold; margin: 2mm 0; }
.digit-row { display: flex; justify-content: center; gap: 2mm; margin: 6mm 0; }
.digit-box { border: 1px solid #333; border-radius: 2px; width: 8mm; height: 11mm;
             display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 11pt; }
.instructions { border: 1px solid #999; border-radius: 4px; padding: 6mm; margin: 10mm auto;
                width: 160mm; font-size: 8pt; text-align: left; color: #333; }
.instructions li { margin-bottom: 2mm; }
.subject-header { text-align: center; font-weight: bold; font-size: 12pt; border-bottom: 1px solid #999;
                   padding-bottom: 2mm; margin-bottom: 6mm; }
.question { margin-bottom: 5mm; page-break-inside: avoid; }
.question-head { display: flex; gap: 2mm; }
.q-number { font-weight: bold; min-width: 6mm; }
.options { margin-left: 8mm; margin-top: 1.5mm; }
.option { margin-bottom: 1mm; }
.option-letter { font-weight: bold; }
img.latex-inline { vertical-align: middle; height: 3.4mm; }
img.question-image { display: block; max-width: 100%; margin: 2mm 0; }
"""


def build_booklet_html(
    student: dict, exam_id: str, booklet_id: str,
    rendered_questions: list[dict], brand_name: str = "BRAND NAME",
) -> str:
    """rendered_questions -- randomization.build_shuffled_booklet() natijasi."""

    fanlar_str = ", ".join(sorted({q["fan"] for q in rendered_questions}))

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
        </div>
        <div style="font-size:7pt;color:#666;">SAVOL ID (bu raqamni javoblar varag'iga ham bo'yab belgilang)</div>
        {_digit_boxes_html(booklet_id)}
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
        questions_html = "".join(_question_html(q["display_tartib"], q) for q in qs)
        body_pages.append(
            f'<div class="subject-header">{fan}</div>{questions_html}<div style="page-break-after: always;"></div>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{_PAGE_CSS}</style></head>
<body>{cover_html}{''.join(body_pages)}</body></html>"""


def render_booklet_pdf(
    student: dict, exam_id: str, booklet_id: str,
    rendered_questions: list[dict], output_path: str, brand_name: str = "BRAND NAME",
) -> str:
    html = build_booklet_html(student, exam_id, booklet_id, rendered_questions, brand_name=brand_name)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(output_path)
    return output_path