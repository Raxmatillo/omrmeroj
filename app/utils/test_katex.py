# test_katex.py
from latex_render import render_math_to_data_uri

formula = r"z=\cos^2x+\sqrt{x^3+4\cdot c}-\left(\frac{12}{15}+ \frac{11}{15}\right)^2"
result = render_math_to_data_uri(formula)

if result:
    print("✅ Muvaffaqiyatli! Data URI bosh qismi:", result[:60])
    # Brauzerda ko'rish uchun HTML fayl
    with open("test_formula.html", "w", encoding="utf-8") as f:
        f.write(f'<html><body><img src="{result}" alt="formula"></body></html>')
    print("📄 test_formula.html yaratildi. Brauzerda oching.")
else:
    print("❌ Xatolik! render_math_to_data_uri 'None' qaytardi.")