# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import logging
import re
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
from matplotlib import mathtext

logger = logging.getLogger(__name__)

_LATEX_INLINE_RE = re.compile(r"\\\((.+?)\\\)")
_LATEX_BLOCK_RE = re.compile(r"\\\[(.+?)\\\]")

_FRAC_FIX_RE = re.compile(r"\\frac(\d+)(\d+)")


def _fix_latex(expr: str) -> str:
    expr = _FRAC_FIX_RE.sub(r"\\frac{\1}{\2}", expr)
    expr = expr.replace(r"\left", "").replace(r"\right", "")
    return expr


def render_math_to_data_uri(latex_expr: str, fontsize: float = 12, dpi: int = 300) -> str:
    try:
        expr = _fix_latex(latex_expr)
        buf = BytesIO()
        mathtext.math_to_image(
            f"${expr}$", buf, dpi=dpi, format="png",
            prop=matplotlib.font_manager.FontProperties(size=fontsize),
        )
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    except Exception as e:
        logger.warning(f"LaTeX render xatolik: {latex_expr} -> {e}")
        return None


def render_latex_in_html(html: str | None, fontsize: float = 12, dpi: int = 300) -> str:
    if not html:
        return ""

    def _replace_inline(match: re.Match) -> str:
        expr = match.group(1).strip()
        data_uri = render_math_to_data_uri(expr, fontsize=fontsize, dpi=dpi)
        if data_uri:
            return f'<img class="latex-inline" src="{data_uri}" alt="{expr}">'
        else:
            return f'<code>${expr}$</code>'

    def _replace_block(match: re.Match) -> str:
        expr = match.group(1).strip()
        data_uri = render_math_to_data_uri(expr, fontsize=fontsize + 2, dpi=dpi)
        if data_uri:
            return f'<div class="latex-block"><img class="latex-block-img" src="{data_uri}" alt="{expr}"></div>'
        else:
            return f'<pre>${expr}$</pre>'

    html = _LATEX_INLINE_RE.sub(_replace_inline, html)
    html = _LATEX_BLOCK_RE.sub(_replace_block, html)
    return html