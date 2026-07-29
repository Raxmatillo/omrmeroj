# OMR Meroj -- Backend (Phase 2: Test System)

## Ishga tushirish

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # kerak bo'lsa DATABASE_URL/SUPABASE'ni o'zgartiring

uvicorn app.main:app --reload --port 8000
```

Brauzerda: http://localhost:8000/docs -- barcha endpointlarni shu yerdan
qo'lda sinab ko'rishingiz mumkin (Swagger UI).

Ucdan-uchga sinash uchun: `python smoke_test.py` (server ishga tushirilgan
bo'lishi shart emas, TestClient orqali to'g'ridan-to'g'ri ishlaydi).

## Hozir nima ishlaydi

- `POST /auth/dev-register` -- lokal test uchun (Telegram bot tayyor
  bo'lgach o'chiriladi / DEV_MODE=false qilinadi)
- `POST /auth/login`, `GET /auth/me` -- JWT (15 kun)
- `Guruhlar` -- CRUD + talaba qo'shish
- `Testlar → Variantlar → Savollar` -- to'liq CRUD, admin panel shu
  API'larga ulanadi. Variant nusxalash (`duplicate`) ham bor.
- `POST /tests/variants/{id}/import-excel` -- eski Excel shabloni orqali
  tezkor matnli savol qo'shish (rasm/formula kerak bo'lmasa)
- `POST /uploads/question-image` -- rasm yuklash. Supabase sozlanmagan
  bo'lsa lokal papkaga saqlaydi (dev fallback), `.env`ga
  `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` qo'yilsa avtomatik Supabase
  Storage'ga o'tadi -- boshqa hech narsani o'zgartirish shart emas.

## Hali yo'q (keyingi bosqichlar)

- Imtihon yaratish (`Exam`) -- guruh+test+variant biriktirish, booklet
  (WeasyPrint, HTML) va javoblar varag'i (reportlab -- sizning
  `answer_sheet_generator.py`) generatsiya qilish, ZIP yig'ish
- Natijalar -- sizning `omr_reader.py`ni servis sifatida ulash, haqiqiy
  javob kaliti bilan solishtirib baholash, natija PDF
- Telegram bot orqali ro'yxatdan o'tish (hozir DEV_MODE bilan chetlab
  o'tilgan)
- Alembic migratsiyalar (hozir `Base.metadata.create_all` bilan jadval
  yaratiladi -- ishlaydi, lekin schema o'zgarganda eski ma'lumot
  yo'qolishi mumkin, shuning uchun productiondan oldin Alembic'ga
  o'tish tavsiya etiladi)

## Papka tuzilishi

```
app/
  config.py       -- barcha sozlamalar (.env orqali)
  database.py     -- SQLAlchemy engine/session
  models.py       -- User, Group, Student, TestSet, Variant, Question,
                     Exam, ExamStudent, Result, ProcessingJob
  schemas.py      -- Pydantic request/response
  security.py     -- parol hash, JWT
  deps.py         -- get_current_user, require_teacher, require_superadmin
  main.py         -- FastAPI app
  routers/
    auth.py
    groups.py
    tests.py
    uploads.py
  utils/
    excel_import.py
```

## Supabase'ga o'tish

1. Supabase'da loyiha yarating, Postgres connection string'ni oling.
2. `.env`da `DATABASE_URL=postgresql://...` qiling.
3. Storage'da `question-images` bucket yarating (public read), Service
   Role key'ni `SUPABASE_SERVICE_KEY`ga qo'ying.
4. Boshqa hech narsa o'zgarmaydi -- kod allaqachon shu ikkalasiga
   moslab yozilgan.
