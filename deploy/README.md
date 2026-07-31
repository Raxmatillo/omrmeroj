# Telegram bot + OMR integratsiyasi -- o'rnatish va production'ga chiqarish

## 1. Fayllarni joylashtirish

Ushbu patch'dagi fayllarni repo ichidagi bir xil yo'llarga ko'chiring
(mavjudlarini almashtiradi, yangilarini qo'shadi):

```
app/config.py               -- almashtiring
app/models.py                -- almashtiring
app/schemas.py                -- almashtiring
app/security.py                -- almashtiring
app/routers/auth.py           -- almashtiring
app/services/__init__.py      -- yangi
app/services/telegram.py      -- yangi
app/services/omr_service.py   -- yangi
app/omr/                       -- YANGI PAPKA (pastga qarang)
bot/                             -- butunlay yangi papka
requirements.txt              -- almashtiring
.env.example                  -- almashtiring
deploy/                         -- yangi (systemd unit'lar)
```

### `app/omr/` -- sizning 4 ta skriptingiz shu yerga joylanadi

Siz yuborgan fayllar (`omr_reader.py`, `answer_sheet_generator.py`,
`generate_question_booklet.py`, `excel_loader.py`) O'ZGARTIRILMAGAN
holda (faqat bittasida bitta import qatori tuzatilgan, pastga qarang)
`app/omr/` papkasiga joylashtirilgan -- bu patch ichida allaqachon shu
tarzda tayyorlab qo'yilgan:

```
app/omr/__init__.py                     -- bo'sh, paket sifatida belgilash uchun
app/omr/omr_reader.py                   -- sizning fayl, o'zgarishsiz
app/omr/answer_sheet_generator.py       -- sizning fayl, o'zgarishsiz
app/omr/generate_question_booklet.py    -- sizning fayl, FAQAT 1 QATOR o'zgargan:
                                            "from excel_loader import ..." ->
                                            "from app.omr.excel_loader import ..."
                                            (chunki endi paket ichida joylashgan)
app/omr/excel_loader.py                 -- sizning fayl, o'zgarishsiz
```

`app/services/omr_service.py` shu paketdagi `omr_reader.detect_answer_sheet()`
funksiyasini to'g'ridan-to'g'ri chaqiradi -- bubble-aniqlash, perspective
correction va QR o'qishning o'zi sizning kodingizda qoladi, men uni
qayta yozmadim.

## 2. Tizim kutubxonalari (pdf2image uchun shart)

`pdf2image` ichki `poppler` (pdftoppm) dasturiga tayanadi:

```bash
# Ubuntu/Debian
sudo apt-get install -y poppler-utils

# macOS
brew install poppler
```

QR o'qish uchun endi qo'shimcha tizim kutubxonasi (`libzbar` va h.k.)
KERAK EMAS -- `omr_reader.py` OpenCV'ning o'rnatilgan `QRCodeDetector`'idan
foydalanadi, u `opencv-python-headless` paketi bilan birga keladi.

## 3. .env

```bash
cp .env.example .env
```

To'ldiring:
- `TELEGRAM_BOT_TOKEN` -- @BotFather'dan olingan token
- Productionga chiqishdan oldin `DEV_MODE=false`

## 4. Bog'liqliklarni o'rnatish

```bash
pip install -r requirements.txt
```

## 5. Lokal ishga tushirish (2 ta alohida terminal)

```bash
# 1-terminal: API
uvicorn app.main:app --reload --port 8000

# 2-terminal: Bot
python -m bot.main
```

## 6. Muhim: Exam/booklet yaratish endpointlari hali yo'q

`app/omr/answer_sheet_generator.py` va `app/omr/generate_question_booklet.py`
hozircha faqat **javob varag'ini tekshirish** yo'nalishida (`omr_service.py`
orqali) ishlatilyapti -- ya'ni `ExamStudent.answer_key_json` DB'da
qandaydir yo'l bilan allaqachon mavjud bo'lishi kerak.

Booklet/javob varag'i PDF'larini yaratib, `answer_key_json`ni DB'ga
yozadigan `/exams` endpoint hali yozilmagan (README'dagi "Hali yo'q"
bo'limiga qarang). Xohlasangiz, keyingi qadam sifatida shuni ham
qo'shib beraman -- bu quyidagilarni o'z ichiga oladi:
- `POST /exams` -- guruh + test to'plamini biriktirib, har bir talaba
  uchun booklet_id generatsiya qilish
- Har bir talaba uchun `generate_question_booklet.build()` va
  `answer_sheet_generator.generate_answer_sheet()` chaqirish, natijalarni
  ZIP qilib qaytarish
- `answer_key_json`ni `generate_question_booklet.build()` qaytargan
  formatda (`correct_letter_shown_to_student` maydoni bilan) to'g'ridan-
  to'g'ri saqlash -- `omr_service.py` allaqachon shu formatni kutadi.

## 7. Production (systemd, VPS misolida)

```bash
sudo useradd -r -s /bin/false omrmeroj
sudo mkdir -p /opt/omrmeroj
sudo cp -r . /opt/omrmeroj
cd /opt/omrmeroj
sudo python3 -m venv .venv
sudo ./.venv/bin/pip install -r requirements.txt
sudo cp .env.example .env   # va to'ldiring
sudo chown -R omrmeroj:omrmeroj /opt/omrmeroj

sudo cp deploy/omrmeroj-api.service /etc/systemd/system/
sudo cp deploy/omrmeroj-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now omrmeroj-api
sudo systemctl enable --now omrmeroj-bot

# Loglarni kuzatish
journalctl -u omrmeroj-api -f
journalctl -u omrmeroj-bot -f
```

API'ni tashqi dunyoga chiqarish uchun oldiga Nginx + Let's Encrypt (HTTPS)
qo'yish tavsiya etiladi. Bot esa hech qanday ochiq portga muhtoj emas
(long polling -- Telegram serverlariga o'zi ulanadi), shuning uchun
firewall/Nginx sozlash shart emas.

## 8. Webhook rejimiga o'tish (ixtiyoriy, kelajakda)

Yuqoridagi bot `long polling` bilan ishlaydi -- bu VPS uchun eng oddiy va
ishonchli variant. Agar keyinchalik yuqori yuklama bo'lsa, aiogram'ning
webhook rejimiga o'tish mumkin (bot handlerlarining o'zi o'zgarmaydi,
faqat `bot/main.py`dagi ishga tushirish qismi FastAPI ichiga webhook route
sifatida ko'chadi).


.venv/bin/alembic upgrade head