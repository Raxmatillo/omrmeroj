# -*- coding: utf-8 -*-
"""
savol_html / variant_x_html ichidagi $...$ LaTeX ifodalarini PDF'da
ko'rsatish uchun.

WeasyPrint MathML yoki LaTeX'ni to'g'ridan-to'g'ri render qila olmaydi
(faqat HTML+CSS). Shuning uchun har bir $...$ segment matplotlib'ning
`mathtext` mexanizmi orqali kichik PNG rasmga aylantiriladi va HTML
ichiga <img> sifatida qo'yiladi -- Node/KaTeX kabi tashqi jarayon shart
emas.
"""
from __future__ import annotations

import base64
import re
from io import BytesIO

import matplotlib
matplotlib.use("Agg")  # server muhitida GUI kerak emas
from matplotlib import mathtext

_LATEX_INLINE_RE = re.compile(r"\$([^$]+)\$")

_parser = mathtext.MathTextParser("agg")


def render_math_to_data_uri(latex_expr: str, fontsize: float = 11, dpi: int = 200) -> str:
    buf = BytesIO()
    _parser.to_png(buf, f"${latex_expr}$", fontsize=fontsize, dpi=dpi)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_latex_in_html(html: str | None, fontsize: float = 11, dpi: int = 200) -> str:
    """$...$ ichidagi barcha LaTeX ifodalarni <img> teglariga almashtiradi.
    Bo'sh/None bo'lsa bo'sh string qaytaradi (savol_rasm_url/jadval_html
    kabi ixtiyoriy maydonlar uchun)."""
    if not html:
        return ""

    def _replace(match: re.Match) -> str:
        expr = match.group(1)
        try:
            data_uri = render_math_to_data_uri(expr, fontsize=fontsize, dpi=dpi)
        except Exception:
            # Render qilib bo'lmasa, sahifa butunlay qulamasin -- asl
            # matnni saqlab qolamiz, o'qituvchi buni ko'rib tuzatadi.
            return match.group(0)
        return f'<img class="latex-inline" src="{data_uri}" alt="{expr}">'

    return _LATEX_INLINE_RE.sub(_replace, html)