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

# ============================================================
# YANGI CRUD ENDPOINTLAR
# ============================================================

print("12) bulk add students")
bulk_result = call("post", f"/groups/{group['id']}/students/bulk", json={
    "students": [
        {"first_name": "Jasur", "last_name": "Aliyev"},
        {"first_name": "Madina", "last_name": "Rahimova"},
    ]
}, headers=H)
print("   -> qo'shildi:", len(bulk_result))
extra_student_1, extra_student_2 = bulk_result

print("13) update student")
updated_student = call("put", f"/groups/{group['id']}/students/{student['id']}",
                        json={"middle_name": "Baxtiyor qizi"}, headers=H)
print("   -> middle_name:", updated_student["middle_name"])

print("14) soft-delete student (deactivate)")
soft_del = call("delete", f"/groups/{group['id']}/students/{extra_student_1['id']}", headers=H)
print("   ->", soft_del)

print("15) hard-delete student")
hard_del = call("delete", f"/groups/{group['id']}/students/{extra_student_2['id']}?hard=true", headers=H)
print("   ->", hard_del)

print("16) update group")
updated_group = call("put", f"/groups/{group['id']}", json={"description": "yangilangan tavsif"}, headers=H)
print("   -> description:", updated_group["description"])

print("17) update test set")
updated_ts = call("put", f"/tests/{ts['id']}", json={"name": "Yakuniy nazorat (yangilangan)"}, headers=H)
print("   -> name:", updated_ts["name"])

print("18) delete variant (nusxa variant2 ni o'chiramiz)")
del_variant = call("delete", f"/tests/variants/{variant2['id']}", headers=H)
print("   ->", del_variant)

print("19) delete exam (mavjud bo'lmagan id -- 404 kutiladi)")
r = client.delete("/exams/nonexistent-id", headers=H)
assert r.status_code == 404, f"Kutilmagan status: {r.status_code}: {r.text}"
print("   -> 404 to'g'ri qaytdi")

print("20) delete result (mavjud bo'lmagan id -- 404 kutiladi)")
r = client.delete("/results/nonexistent-id", headers=H)
assert r.status_code == 404, f"Kutilmagan status: {r.status_code}: {r.text}"
print("   -> 404 to'g'ri qaytdi")

print("21) update profile")
updated_me = call("put", "/auth/me", json={"full_name": "Yangilangan Ism"}, headers=H)
print("   -> full_name:", updated_me["full_name"])

print("22) change password")
new_token = call("post", "/auth/change-password",
                  json={"old_password": "test1234", "new_password": "newpass123"}, headers=H)["access_token"]
H = {"Authorization": f"Bearer {new_token}"}
print("   -> parol yangilandi, yangi token olindi")

print("23) delete test set (cascade: variants + questions)")
del_ts = call("delete", f"/tests/{ts['id']}", headers=H)
print("   ->", del_ts)

print("24) delete group (cascade: students)")
del_group = call("delete", f"/groups/{group['id']}", headers=H)
print("   ->", del_group)

print("\nHAMMASI OK")