# -*- coding: utf-8 -*-
import io
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def call(method, url, **kw):
    r = getattr(client, method)(url, **kw)
    assert r.status_code < 400, f"{method.upper()} {url} -> {r.status_code}: {r.text}"
    return r.json()


print("1) dev-register")
call("post", "/auth/dev-register", json={"phone": "+998901234567", "password": "test1234", "full_name": "Test O'qituvchi"})

print("2) login")
token = call("post", "/auth/login", json={"phone": "+998901234567", "password": "test1234"})["access_token"]
H = {"Authorization": f"Bearer {token}"}

print("3) me")
me = call("get", "/auth/me", headers=H)
print("   ->", me)

print("4) create group")
group = call("post", "/groups", json={"name": "10-A", "description": "demo"}, headers=H)

print("5) add student")
student = call("post", f"/groups/{group['id']}/students",
                json={"first_name": "Nilufar", "last_name": "Karimova"}, headers=H)

print("6) create test set")
ts = call("post", "/tests", json={"name": "Yakuniy nazorat", "total_questions": 30}, headers=H)

print("7) create variant")
variant = call("post", f"/tests/{ts['id']}/variants", json={"label": "1-variant"}, headers=H)

print("8) add question manually (admin panel yo'li)")
q = call("post", f"/tests/variants/{variant['id']}/questions", json={
    "tartib": 1, "fan": "Matematika", "ball": 1.1,
    "savol_html": "2x + 5 = 17 tenglamada $x$ ni toping.",
    "variant_a_html": "5", "variant_b_html": "6", "variant_c_html": "7", "variant_d_html": "8",
    "togri_javob": "b",
}, headers=H)
print("   -> togri_javob saqlandi:", q["togri_javob"])

print("9) duplicate variant")
variant2 = call("post", f"/tests/variants/{variant['id']}/duplicate?new_label=2-variant", headers=H)
print("   -> nusxa savollar soni:", len(variant2["questions"]))

print("10) upload question image (dev fallback)")
img_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 100  # yasama PNG header, faqat oqimni sinash uchun
files = {"file": ("test.png", io.BytesIO(img_bytes), "image/png")}
img = call("post", "/uploads/question-image", files=files, headers=H)
print("   -> url:", img["url"])

print("11) get test set (nested variants+questions)")
full = call("get", f"/tests/{ts['id']}", headers=H)
print("   -> variantlar soni:", len(full["variants"]))

print("\nHAMMASI OK")
