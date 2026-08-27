# -*- coding: utf-8 -*-
"""
savol_html / variant_x_html ichidagi matematik ifodalarni PDF'da
ko'rsatish uchun -- endi pdflatex+PyMuPDF (rasm) EMAS, balki KaTeX
(Node.js, server-side) orqali HTML+CSS sifatida render qilinadi.

NEGA BU YONDASHUVGA O'TILDI (avvalgi rasm-asosli usuldan farqi):

    Avvalgi usulda har bir formula alohida PDF->PNG rasmga aylantirilib,
    <img> sifatida joylashtirilardi. Bu rasm bilan atrofdagi oddiy HTML
    matn o'rtasida umumiy o'lchov tizimi yo'qligiga olib kelardi --
    natijada fontsize, baseline, markazlanish, proporsiya kabi narsalar
    doim qo'lda (fontsize, width_pt/height_pt, scale, vertical-align)
    sozlanishi kerak edi va har bir tuzatish boshqa joyni buzardi.

    KaTeX esa formulani RASM emas, balki oddiy HTML+CSS (span'lar va
    maxsus KaTeX shriftlari) sifatida chiqaradi -- bu HTML atrofdagi
    matn bilan BIR XIL typesetting oqimida, chunki ikkalasi ham xuddi
    shu WeasyPrint dvigateli tomonidan bir xil qoidalar bilan
    joylashtiriladi. Fontsize, baseline, vertikal tekislash -- bularning
    barchasi KaTeX CSS'ining o'zida hal qilingan, bizga qo'lda hisoblash
    shart emas.

MUHIM -- MARKAZLANISH VA "BLOK" HAQIDA:

    displayMode har doim `false` (katex_render.js'ga qarang) -- shu
    sabab formula HECH QACHON o'z-o'zidan yangi qatorga o'tib
    markazlanib qolmaydi. Faqat savol_rasm_url (haqiqiy rasm,
    booklet_html_generator.py'dagi .question-image-wrap) markazda
    bo'ladi -- bu shu faylga aloqasi yo'q, alohida boshqariladi.

    "Katta/to'liq o'lchamli kasr" kerak bo'lgan holatlar (masalan
    mathBlock yoki $$..$$ sifatida yozilgan, lekin aslida gap ichida
    ishlatiladigan formulalar) uchun LaTeX ifodasining o'ziga
    `\\displaystyle` prefiksi qo'shiladi (pastdagi is_block=True
    holatida) -- bu kasr/summa/limitni to'liq o'lchamda chiqaradi,
    lekin baribir INLINE (matn bilan bir qatorda) qoladi.

REGEX PIPELINE HAQIDA (eski izohdan meros, hamon amal qiladi):

    Bu faylda BARCHA format (TipTap <span data-type="mathInline">,
    $$..$$, \\[..\\], \\(..\\), $..$, va argumentsiz "yalang'och"
    \\command) BITTA regex orqali topiladi va BITTA marta almashtiriladi
    (endi re.sub emas, balki formulalarni avval TO'PLAB, Node'ga BATCH
    yuboramiz, keyin natijalarni joylariga QAYTA joylashtiramiz -- lekin
    tamoyil bir xil: manba matni ikki marta skanerlanmaydi, shuning
    uchun oldingi rasm-usulidagi "ikkilanib chiqish" xatosi bu yerda
    ham takrorlanmaydi).
"""
from __future__ import annotations

import html as _html
import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

_ATTR_LATEX_RE = re.compile(r'latex=["\']([^"\']*)["\']')

# YAGONA master regex -- eski latex_render.py bilan bir xil, formulani
# TOPISH mantig'i o'zgargani yo'q, faqat RENDER usuli o'zgardi.
_MASTER_RE = re.compile(
    r'(?P<tiptap><(?P<tag>span|div)\s+(?P<attrs>[^>]*data-type=["\'](?P<mtype>mathInline|mathBlock)["\'][^>]*)>'
    r'(?P<inner>.*?)</(?P=tag)>)'
    r'|(?P<dblock>\$\$.+?\$\$)'
    r'|(?P<block>\\\[.+?\\\])'
    r'|(?P<pinline>\\\(.+?\\\))'
    r'|(?P<dinline>(?<!\\)\$[^$]+?\$)'
    r'|(?P<barecmd>\\[a-zA-Z]+(?:\{[^{}]*\})*)',
    re.DOTALL,
)

# katex_render.js shu papkada joylashgan deb faraz qilinadi. Agar
# boshqa joyga qo'ysangiz, shu yo'lni moslang (yoki env var orqali
# tashqaridan bering).
import sys

_THIS_FILE = os.path.abspath(__file__)  # .../backend/app/utils/latex_render.py


def _dev_project_root() -> str:
    # backend/app/utils -> backend/app -> backend -> omrmeroj-desktop-v2
    return os.path.abspath(os.path.join(os.path.dirname(_THIS_FILE), "..", "..", ".."))


def _resolve_katex_paths() -> tuple[str, str]:
    """Qaytaradi: (katex_render.js yo'li, node_modules papkasi yo'li)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        katex_js = os.path.join(base, "app", "utils", "katex_render.js")
        node_modules = os.path.join(base, "node_modules")
    else:
        utils_dir = os.path.dirname(_THIS_FILE)
        katex_js = os.path.join(utils_dir, "katex_render.js")
        node_modules = os.path.join(_dev_project_root(), "node_modules")
    return katex_js, node_modules


_DEFAULT_KATEX_JS, _DEFAULT_NODE_MODULES = _resolve_katex_paths()
_KATEX_JS_PATH = os.environ.get("KATEX_RENDER_JS_PATH", _DEFAULT_KATEX_JS)
_NODE_MODULES_DIR = os.environ.get("KATEX_NODE_MODULES_DIR", _DEFAULT_NODE_MODULES)

def _fix_latex(expr: str) -> str:
    """Mavjud LaTeX ifodasini KaTeX tushunadigan shaklga keltiradi.
    (Eski pdflatex-uchun yozilgan tuzatishlar bilan deyarli bir xil --
    KaTeX ham standart LaTeX buyruqlarini kutadi.)"""
    if not expr:
        return ""

    expr = re.sub(r'(?<!\\)sqrt\s*\{?(\d+)\}?', r'\\sqrt{\1}', expr, flags=re.IGNORECASE)
    expr = re.sub(r'\[\s*sqrt\s*\{?(\d+)\}?\s*\]', r'\\sqrt{\1}', expr, flags=re.IGNORECASE)
    expr = re.sub(r'(?<!\\)vec\{([^{}]*)\}', r'\\vec{\1}', expr, flags=re.IGNORECASE)
    expr = expr.replace('*', r'\cdot ')
    expr = expr.replace('–', '-').replace('—', '-')
    expr = re.sub(r'(?<!\\)\b(cos|sin|tan|tg|ctg|log|ln|lim)\b', r'\\\1', expr)
    for fn in ["arcsin", "arccos", "arctg", "arcctg", "arctan"]:
        expr = re.sub(rf'(?<!\\){fn}', r'\\operatorname{' + fn + '}', expr)
    expr = re.sub(r'\\frac(\d)(\d)', r'\\frac{\1}{\2}', expr)
    expr = re.sub(r'\\frac(\d)\{(\d+)\}', r'\\frac{\1}{\2}', expr)
    expr = expr.replace(r"\left", "").replace(r"\right", "")
    expr = re.sub(r'\\degree\b', r'^\\circ', expr)

    return expr.strip()


def _extract_expressions(html: str) -> list[dict]:
    """HTML ichidan barcha formula ifodalarini topadi va ularning
    matn ichidagi o'rnini (match obyekti) saqlab qoladi -- keyinroq
    natijalarni aynan shu joylarga qaytarib qo'yish uchun."""
    items = []
    for m in _MASTER_RE.finditer(html):
        gd = m.groupdict()

        if gd.get("tiptap"):
            attrs = gd["attrs"]
            inner = gd["inner"]
            mtype = gd["mtype"]
            am = _ATTR_LATEX_RE.search(attrs)
            expr = _html.unescape(am.group(1)).strip() if am else _html.unescape(
                re.sub(r"<[^>]+>", "", inner)
            ).strip()
            is_block = mtype == "mathBlock"
        elif gd.get("dblock"):
            expr = gd["dblock"][2:-2].strip().replace("\n", " ")
            is_block = True
        elif gd.get("block"):
            expr = gd["block"][2:-2].strip().replace("\n", " ")
            is_block = True
        elif gd.get("pinline"):
            expr = gd["pinline"][2:-2].strip().replace("\n", " ")
            is_block = False
        elif gd.get("dinline"):
            expr = gd["dinline"][1:-1].strip().replace("\n", " ")
            is_block = False
        elif gd.get("barecmd"):
            expr = gd["barecmd"].strip()
            is_block = False
        else:
            continue

        items.append({
            "match": m,
            "raw_expr": expr,
            "is_block": is_block,
        })

    return items


def _call_katex_node(payload: list[dict]) -> list[dict]:
    if not payload:
        return []

    env = os.environ.copy()
    env["NODE_PATH"] = _NODE_MODULES_DIR

    try:
        proc = subprocess.run(
            ["node", _KATEX_JS_PATH],
            input=json.dumps(payload).encode("utf-8"),   # <-- text=True EMAS, xom bayt
            capture_output=True,
            timeout=30,
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        stderr_text = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        logger.error(f"katex_render.js xato bilan tugadi: {stderr_text}")
        return [{"id": p["id"], "error": "node process failed"} for p in payload]
    except subprocess.TimeoutExpired:
        logger.error("katex_render.js timeout")
        return [{"id": p["id"], "error": "timeout"} for p in payload]
    except FileNotFoundError:
        logger.error("node topilmadi yoki katex_render.js yo'q: %s", _KATEX_JS_PATH)
        return [{"id": p["id"], "error": "node not found"} for p in payload]

    try:
        stdout_text = proc.stdout.decode("utf-8", errors="replace")   # <-- aniq UTF-8
        return json.loads(stdout_text)
    except json.JSONDecodeError:
        logger.error(f"katex_render.js noto'g'ri JSON qaytardi: {proc.stdout[:500]!r}")
        return [{"id": p["id"], "error": "invalid json output"} for p in payload]

def _fallback_html(expr: str) -> str:
    """Render muvaffaqiyatsiz bo'lsa, sahifa butunlay qulamasin deb,
    escape qilingan xom matnni <code> ichida ko'rsatamiz."""
    safe = _html.escape(expr)
    return f'<code>${safe}$</code>'


def render_latex_in_html(html: str | None, fontsize: float = 11, dpi: int = 150) -> str:
    """
    HTML ichidagi barcha matematik ifodalarni KaTeX orqali (Node.js,
    server-side, bitta BATCH chaqiruvda) HTML+CSS'ga aylantiradi.

    `dpi` parametri endi ishlatilmaydi (rasm emas, vektor/shrift asosli
    render) -- faqat eski chaqiruv joylari (booklet_html_generator.py)
    bilan moslik uchun signature'da qoldirilgan, e'tiborsiz qoldiriladi.

    `fontsize` -- formulaning nisbiy o'lchamini boshqaradi (em bo'yicha
    inline style orqali qo'llaniladi; asosiy hujjat shrifti odatda
    ~12pt bo'lgani uchun fontsize=11 taxminan 0.9em'ga to'g'ri keladi,
    formula matndan sal kichikroq/tengroq chiqishi uchun quyida
    nisbatlangan).
    """
    if not html:
        return ""

    items = _extract_expressions(html)
    if not items:
        return html

    # Har bir ifodani normalizatsiya qilib, KaTeX'ga yuboriladigan
    # payload'ni tayyorlaymiz. is_block=True bo'lsa \displaystyle
    # prefiksi qo'shiladi -- shunda kasr/summa to'liq o'lchamda
    # chiqadi, lekin displayMode HAMON false (katex_render.js'da),
    # shuning uchun formula baribir matn bilan bir qatorda qoladi,
    # markazlanmaydi.
    payload = []
    for idx, it in enumerate(items):
        fixed = _fix_latex(it["raw_expr"])
        if not fixed:
            it["skip"] = True
            continue
        it["skip"] = False
        it["id"] = idx
        expr_for_katex = r"\displaystyle " + fixed
        payload.append({"id": idx, "expr": expr_for_katex, "display": False})

    results_by_id = {}
    if payload:
        results = _call_katex_node(payload)
        for r in results:
            results_by_id[r["id"]] = r

    # Nisbiy shrift o'lchami: hujjatning asosiy shrifti (12pt) ga
    # nisbatan fontsize/12 nisbatida em beriladi.
    rel_size = round(fontsize / 12.0, 3)

    # Endi natijalarni asl matndagi joylariga QAYTARIB qo'yamiz --
    # oxiridan boshiga qarab almashtiramiz, shunda oldingi
    # almashtirishlar keyingi match.span() indekslarini buzmaydi.
    out = html
    
    for idx in range(len(items) - 1, -1, -1):
        it = items[idx]
        m = it["match"]
        if it.get("skip"):
            replacement = ""
        else:
            r = results_by_id.get(it["id"])
            if r is None or "error" in r or not r.get("html"):
                if r and "error" in r:
                    logger.warning(f"KaTeX render xatolik: {it['raw_expr']} -> {r['error']}")
                replacement = _fallback_html(it["raw_expr"])
            else:
                # style="font-size:...em" -- span ichida, KaTeX
                # o'zining ichki nisbatlarini shu asosiy o'lchamdan
                # hisoblab oladi (KaTeX shu tarzda ishlashga
                # mo'ljallangan -- font-size'ni tashqi konteksdan
                # meros oladi).
                replacement = (
                    f'<span class="katex-wrap" style="font-size:{rel_size}em;">'
                    f'{r["html"]}</span>'
                )
        out = out[: m.start()] + replacement + out[m.end():]

    return out