# -*- coding: utf-8 -*-
"""
Oddiy zaxira (backup) skripti.

Nima qiladi:
  1. SQLite bazasi (omrmeroj.db) + generated_files/ papkasini (barcha
     PDF, rasm fayllar) bitta zip'ga yig'adi, sana-vaqt bilan
     nomlaydi, backups/ papkasiga saqlaydi.
  2. Eski zaxiralarni tozalaydi -- faqat oxirgi KEEP_LAST_N tasi
     qoladi (disk to'lib ketmasligi uchun).
  3. Agar .env'da ADMIN_TELEGRAM_CHAT_ID sozlangan bo'lsa, zaxira
     faylini Telegram orqali ham yuboradi -- bu KOMPYUTER BUZILSA
     YOKI DISK SHIKASTLANSA HAM zaxiraning bir nusxasi xavfsiz joyda
     (Telegram serverlarida) qolishini ta'minlaydi. Bu qadam
     ixtiyoriy -- agar sozlanmagan bo'lsa, shunchaki o'tkazib
     yuboriladi (xato bermaydi).

ISHLATISH:
    python scripts/backup.py

AVTOMATLASHTIRISH:
    O'QING.md faylidagi "AVTOMATLASHTIRISH" bo'limiga qarang
    (Windows Task Scheduler / Linux-Mac cron).
"""
from __future__ import annotations

import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# Loyiha ildizini sys.path'ga qo'shish -- skript qayerdan ishga
# tushirilishidan qat'i nazar `app.config`ni topa olishi uchun.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
KEEP_LAST_N = 14  # oxirgi 14 ta zaxira saqlanadi (masalan kunlik -> 2 haftalik tarix)


def _sqlite_path_from_url(url: str) -> Path | None:
    """'sqlite:///./omrmeroj.db' -> Path('./omrmeroj.db'). Postgres va
    boshqa DB turlari uchun None qaytaradi (ular alohida zaxira usulini
    talab qiladi -- masalan pg_dump)."""
    m = re.match(r"sqlite:///(.+)", url)
    if not m:
        return None
    return Path(m.group(1))


def create_backup() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    zip_path = BACKUP_DIR / f"omrmeroj_backup_{timestamp}.zip"

    db_path = _sqlite_path_from_url(settings.DATABASE_URL)
    output_dir = Path(settings.OUTPUT_DIR)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if db_path and db_path.exists():
            zf.write(db_path, arcname=db_path.name)
            print(f"  + {db_path.name} ({db_path.stat().st_size / 1024:.0f} KB)")
        elif db_path:
            print(f"  ! OGOHLANTIRISH: baza fayli topilmadi: {db_path}")
        else:
            print("  ! DATABASE_URL SQLite emas (masalan Postgres) -- "
                  "bu skript faqat SQLite bazasini zaxiralaydi. Postgres "
                  "uchun alohida pg_dump kerak bo'ladi.")

        if output_dir.exists():
            file_count = 0
            for f in output_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=str(Path("generated_files") / f.relative_to(output_dir)))
                    file_count += 1
            print(f"  + generated_files/ ({file_count} ta fayl)")
        else:
            print(f"  ! OGOHLANTIRISH: papka topilmadi: {output_dir}")

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"\nZaxira tayyor: {zip_path} ({size_mb:.1f} MB)")
    return zip_path


def prune_old_backups() -> None:
    backups = sorted(BACKUP_DIR.glob("omrmeroj_backup_*.zip"), key=lambda p: p.stat().st_mtime)
    while len(backups) > KEEP_LAST_N:
        oldest = backups.pop(0)
        oldest.unlink()
        print(f"Eski zaxira o'chirildi: {oldest.name}")


def send_to_telegram(zip_path: Path) -> None:
    chat_id = getattr(settings, "ADMIN_TELEGRAM_CHAT_ID", "")
    if not chat_id or not settings.TELEGRAM_BOT_TOKEN:
        print(
            "\nADMIN_TELEGRAM_CHAT_ID yoki TELEGRAM_BOT_TOKEN sozlanmagan -- "
            "Telegram orqali yuborish o'tkazib yuborildi (faqat lokal zaxira "
            "yaratildi). Agar off-site nusxa xohlasangiz, .env'ga "
            "ADMIN_TELEGRAM_CHAT_ID qo'shing (O'QING.md'ga qarang)."
        )
        return

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    if size_mb > 49:
        print(
            f"\nOGOHLANTIRISH: zaxira {size_mb:.1f}MB -- Telegram Bot API "
            f"50MB limitiga yaqin/oshiq bo'lishi mumkin, yuborish o'tkazib "
            f"yuborildi. Faqat lokal zaxira yaratildi."
        )
        return

    import httpx

    url = f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendDocument"
    with open(zip_path, "rb") as f:
        try:
            resp = httpx.post(
                url,
                data={"chat_id": chat_id, "caption": f"📦 Zaxira: {zip_path.name}"},
                files={"document": (zip_path.name, f, "application/zip")},
                timeout=120,
            )
            if resp.status_code == 200:
                print("Telegram orqali muvaffaqiyatli yuborildi.")
            else:
                print(f"Telegram yuborishda xato: {resp.status_code} {resp.text}")
        except Exception as e:  # noqa: BLE001
            print(f"Telegram yuborishda xato: {e}")


if __name__ == "__main__":
    print("Zaxira yaratilmoqda...\n")
    _zip_path = create_backup()
    prune_old_backups()
    send_to_telegram(_zip_path)
    print("\nTugadi.")
