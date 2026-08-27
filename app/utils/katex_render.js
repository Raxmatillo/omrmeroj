#!/usr/bin/env node
/**
 * KaTeX server-side batch renderer.
 *
 * Nega BATCH (bir martada ko'p formula)?
 *   Node process'ni ishga tushirish (~50-100ms) o'zi bir xarajat.
 *   Agar har bir formula uchun alohida `node katex_render.js` chaqirilsa,
 *   yuzlab formula bo'lgan kitobchada bu xarajat ko'payib ketadi. Shu
 *   sabab Python tomonidan BITTA chaqiruvda BARCHA formulalar ro'yxati
 *   JSON sifatida stdin orqali beriladi, natija ham bitta JSON sifatida
 *   stdout'ga yoziladi.
 *
 * Kirish (stdin, JSON):
 *   [{"id": 0, "expr": "\\frac{a}{b}", "display": false}, ...]
 *
 * Chiqish (stdout, JSON):
 *   [{"id": 0, "html": "<span class=\"katex\">...</span>"}, ...]
 *   Xato bo'lsa: {"id": 0, "error": "..."}
 *
 * MUHIM: displayMode har doim `false` beriladi -- KaTeX'ning o'zi
 * displayMode=true bo'lganda natijani <span class="katex-display">
 * (display:block, avtomatik markazlangan) ichiga o'raydi. Bizga esa
 * formula HECH QACHON o'z-o'zidan yangi qatorga o'tib, markazlanib
 * qolmasligi kerak (faqat savol_rasm_url rasmlari markazda bo'lishi
 * kerak, formulalar EMAS). "Katta/to'liq o'lchamli kasr" kerak bo'lsa,
 * buning o'rniga LaTeX ifodasining o'ziga `\displaystyle` prefiks
 * qo'shiladi (Python tomonida, expr yuborilishidan oldin) -- bu esa
 * kasr/summa/limitni to'liq o'lchamda chiqaradi, lekin baribir INLINE
 * (span, matn bilan bir qatorda) qoladi.
 */

const katex = require("katex");

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

async function main() {
  const raw = await readStdin();
  let items;
  try {
    items = JSON.parse(raw);
  } catch (e) {
    process.stderr.write("KIRISH JSON XATO: " + e.message + "\n");
    process.exit(1);
  }

  const results = items.map((item) => {
    try {
      const html = katex.renderToString(item.expr, {
        throwOnError: false,
        errorColor: "#cc0000",
        displayMode: false, // izohga qarang -- doim false
        strict: "ignore",
        trust: false,
        output: "html",
      });
      return { id: item.id, html };
    } catch (e) {
      return { id: item.id, error: String(e && e.message ? e.message : e) };
    }
  });

  process.stdout.write(JSON.stringify(results));
}

main().catch((e) => {
  process.stderr.write("KUTILMAGAN XATO: " + (e && e.stack ? e.stack : e) + "\n");
  process.exit(1);
});