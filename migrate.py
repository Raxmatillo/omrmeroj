# migrate_full.py - jadvalni qayta yaratish (ma'lumotlarni saqlab)
import sqlite3
from app.config import get_user_data_dir

db_path = get_user_data_dir() / 'omrmeroj.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. Yangi jadval yaratish
cursor.execute("""
    CREATE TABLE question_bank_items_new (
        id VARCHAR PRIMARY KEY,
        teacher_id VARCHAR NOT NULL,
        fan_id VARCHAR NOT NULL,
        kitob_nomi VARCHAR,
        bolim_nomi VARCHAR,
        savol_html TEXT NOT NULL,
        savol_rasm_url VARCHAR,
        savol_rasm_style VARCHAR DEFAULT 'medium',
        jadval_html TEXT,
        variant_a_html TEXT NOT NULL,
        variant_b_html TEXT NOT NULL,
        variant_c_html TEXT NOT NULL,
        variant_d_html TEXT NOT NULL,
        togri_javob VARCHAR(1) NOT NULL,
        ball FLOAT DEFAULT 1.1,
        times_shown INTEGER DEFAULT 0,
        times_correct INTEGER DEFAULT 0,
        difficulty_percent FLOAT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME,
        FOREIGN KEY(teacher_id) REFERENCES users(id),
        FOREIGN KEY(fan_id) REFERENCES fans(id)
    )
""")

# 2. Ma'lumotlarni ko'chirish
cursor.execute("""
    INSERT INTO question_bank_items_new 
    SELECT id, teacher_id, fan, kitob_nomi, bolim_nomi, 
           savol_html, savol_rasm_url, savol_rasm_style, jadval_html,
           variant_a_html, variant_b_html, variant_c_html, variant_d_html,
           togri_javob, ball, times_shown, times_correct, 
           difficulty_percent, created_at, updated_at
    FROM question_bank_items
""")

# 3. Eski jadvalni o'chirish
cursor.execute("DROP TABLE question_bank_items")

# 4. Yangi jadval nomini o'zgartirish
cursor.execute("ALTER TABLE question_bank_items_new RENAME TO question_bank_items")

conn.commit()
conn.close()
print("✅ Jadval muvaffaqiyatli yangilandi, ma'lumotlar saqlanib qoldi!")