# -*- coding: utf-8 -*-
"""
Lokal SQLite bazasidan (mavjud omrmeroj.db) yangi PostgreSQL (masalan
Supabase) bazasiga BARCHA MA'LUMOTNI ko'chiradi.

ISHLATISH:
  1. Yangi (Supabase) bazada avval sxema yaratilgan bo'lishi kerak:
       DATABASE_URL_OVERRIDE=postgresql://... alembic upgrade head
  2. Shundan keyin shu skriptni ishga tushiring:
       python migrate_to_postgres.py "sqlite:///C:/Users/.../omrmeroj.db" "postgresql://postgres:PAROL@db.xxxxx.supabase.co:5432/postgres"

XAVFSIZLIK:
  - Bu skript FAQAT o'qiydi (SELECT) eski SQLite bazadan -- uni hech
    qanday o'zgartirmaydi yoki o'chirmaydi. Eski baza faylingiz
    butunlay saqlanib qoladi, xohlagan vaqt qayta urinib ko'rishingiz
    mumkin.
  - Yangi (maqsad) bazada jadvallar BO'SH bo'lishi kerak (yangi
    yaratilgan, hali hech qanday yozuv yo'q) -- aks holda unique
    constraint xatolari chiqishi mumkin (masalan bir xil ID ikki marta
    yozilsa).
  - Jadvallar SQLAlchemy modelidagi FK (tashqi kalit) bog'liqligiga
    qarab AVTOMATIK to'g'ri tartibda ko'chiriladi (masalan avval
    "users", keyin "groups", keyin "students" -- foydalanuvchi sxema
    o'zgarganda ham qo'lda tartib yozish shart emas).
"""
import sys

from sqlalchemy import create_engine, select

sys.path.insert(0, ".")  # app/ papkasi joylashgan katalogdan ishga tushirilishi kerak
from app.models import Base  # noqa: E402


def migrate(sqlite_url: str, postgres_url: str) -> None:
    src_engine = create_engine(sqlite_url)
    # YANGI: connect_timeout -- agar tarmoq/firewall portni bloklasa,
    # DASTUR CHEKSIZ KUTMASDAN 10 soniyadan keyin ANIQ XATO bilan
    # to'xtaydi (avvalgi versiyada bu yo'q edi -- shuning uchun
    # terminal "qotib qolgan"day ko'rinardi).
    dst_engine = create_engine(postgres_url, connect_args={"connect_timeout": 10})

    metadata = Base.metadata
    total_rows = 0

    with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
        for table in metadata.sorted_tables:  # FK bog'liqligiga qarab to'g'ri tartib
            rows = src_conn.execute(select(table)).mappings().all()
            if not rows:
                print(f"  {table.name:30s} -- bo'sh, o'tkazib yuborildi")
                continue

            dst_conn.execute(table.insert(), [dict(r) for r in rows])
            total_rows += len(rows)
            print(f"  {table.name:30s} -- {len(rows)} ta yozuv ko'chirildi")

    print(f"\nJAMI: {total_rows} ta yozuv muvaffaqiyatli ko'chirildi.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Ishlatish: python migrate_to_postgres.py <sqlite_url> <postgres_url>")
        print('Masalan: python migrate_to_postgres.py "sqlite:///C:/Users/.../omrmeroj.db" "postgresql://postgres:PAROL@db.xxxxx.supabase.co:5432/postgres"')
        sys.exit(1)

    migrate(sys.argv[1], sys.argv[2])
