# -*- coding: utf-8 -*-
"""
Imtihon generatsiyasi test skripti.

Excel format:
    T/r | Fan | Savol | A | B | C | D | To'g'ri javob | Ball

QOIDALAR:
    - 30 ta savol → HAMMASI 1-ustunda (ballga qaramasdan)
    - 60 ta savol → 1.1 ball → 1-ustun, 2.1 ball → 2-ustun
    - 90 ta savol → 1.1 ball → 1-ustun, 2.1 ball → 2-ustun, 3.1 ball → 3-ustun

Ishlatish:
    python test_exam_generator.py
"""

import os
import sys
import random
import secrets
import zipfile
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import json

# Excel faylni o'qish uchun
try:
    import pandas as pd
except ImportError:
    print("❌ Pandas o'rnatilmagan. O'rnatish: pip install pandas openpyxl")
    sys.exit(1)

from app.omr.answer_sheet_generator import (
    Student as SheetStudent,
    Exam as SheetExam,
    SubjectBlock,
    Booklet as SheetBooklet,
    generate_answer_sheet,
)
from app.omr.booklet_html_generator import render_booklet_pdf
from app.omr.randomization import build_shuffled_booklet


# ============================================================
# TEST MA'LUMOTLARI
# ============================================================

TEST_GROUP_NAME = "10-A"
TEST_STUDENTS = [
    {"id": "STU-001", "first_name": "Nilufar", "last_name": "Karimova", "middle_name": "Botir qizi"},
    {"id": "STU-002", "first_name": "Jasur", "last_name": "Aliyev", "middle_name": "Shavkat o'g'li"},
    {"id": "STU-003", "first_name": "Madina", "last_name": "Rahimova", "middle_name": "Anvar qizi"},
    {"id": "STU-004", "first_name": "Aziz", "last_name": "Toshmatov", "middle_name": "Karim o'g'li"},
    {"id": "STU-005", "first_name": "Gulnoza", "last_name": "Sultonova", "middle_name": "Bahrom qizi"},
]


# ============================================================
# EXCEL DAN SAVOLLARNI O'QISH
# ============================================================

def read_questions_from_excel(file_path: str) -> List[Dict[str, Any]]:
    """
    Excel fayldan savollarni o'qiydi.
    
    Excel format:
        T/r | Fan | Savol | A | B | C | D | To'g'ri javob | Ball
    """
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Excel fayl topilmadi: {file_path}")
    
    df = pd.read_excel(file_path)
    
    # Kerakli ustunlarni tekshirish (har xil nomlanishlarga moslash)
    column_mapping = {}
    
    # T/r
    for col in ['T/r', 'TR', 'T/R', '№', 'N', 'No']:
        if col in df.columns:
            column_mapping['tartib'] = col
            break
    
    # Fan
    for col in ['Fan', 'fan', 'FAN']:
        if col in df.columns:
            column_mapping['fan'] = col
            break
    
    # Savol
    for col in ['Savol', 'savol', 'Savol matni', 'Savollar']:
        if col in df.columns:
            column_mapping['savol'] = col
            break
    
    # A, B, C, D
    for col in ['A', 'a']:
        if col in df.columns:
            column_mapping['a'] = col
            break
    
    for col in ['B', 'b']:
        if col in df.columns:
            column_mapping['b'] = col
            break
    
    for col in ['C', 'c']:
        if col in df.columns:
            column_mapping['c'] = col
            break
    
    for col in ['D', 'd']:
        if col in df.columns:
            column_mapping['d'] = col
            break
    
    # To'g'ri javob
    for col in ["To'g'ri javob", 'Togri javob', "To'g'ri", 'Javob', 'Correct']:
        if col in df.columns:
            column_mapping['togri_javob'] = col
            break
    
    # Ball
    for col in ['Ball', 'ball', 'BALL']:
        if col in df.columns:
            column_mapping['ball'] = col
            break
    
    # Kerakli ustunlar mavjudligini tekshirish
    required = ['tartib', 'fan', 'savol', 'a', 'b', 'c', 'd', 'togri_javob', 'ball']
    for key in required:
        if key not in column_mapping:
            raise ValueError(f"Excel da '{key}' ustuni topilmadi. Mavjud ustunlar: {list(df.columns)}")
    
    questions = []
    for idx, row in df.iterrows():
        # T/r ni olish
        try:
            tartib = int(row[column_mapping['tartib']])
        except:
            tartib = idx + 1
        
        # Ball ni olish
        try:
            ball = float(row[column_mapping['ball']])
        except:
            ball = 1.1
        
        question = {
            "id": f"Q-{tartib:03d}",
            "tartib": tartib,
            "fan": str(row[column_mapping['fan']]).strip(),
            "ball": ball,
            "savol_html": str(row[column_mapping['savol']]).strip(),
            "savol_rasm_url": None,
            "jadval_html": None,
            "variant_a_html": str(row[column_mapping['a']]).strip(),
            "variant_b_html": str(row[column_mapping['b']]).strip(),
            "variant_c_html": str(row[column_mapping['c']]).strip(),
            "variant_d_html": str(row[column_mapping['d']]).strip(),
            "togri_javob": str(row[column_mapping['togri_javob']]).strip().upper(),
        }
        questions.append(question)
    
    # Tartib bo'yicha saralash
    questions.sort(key=lambda q: q["tartib"])
    
    return questions


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

def _generate_exam_code() -> str:
    return "EX-" + secrets.token_hex(3).upper()


def _generate_booklet_id() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(7))


def _build_subject_blocks(questions: list[dict]) -> list[SubjectBlock]:
    """
    Javoblar varag'idagi fan bloklarini BALL bo'yicha guruhlaydi.
    
    QOIDALAR:
        - 30 ta savol → 1 ta blok (1-30)
        - 60 ta savol → 2 ta blok (1-30, 31-60)
        - 90 ta savol → 3 ta blok (1-30, 31-60, 61-90)
    """
    
    total = len(questions)
    ordered = sorted(questions, key=lambda q: q["tartib"])
    
    if total <= 30:
        # HAMMASI 1 ta blok
        first = ordered[0]
        last = ordered[-1]
        
        # Barcha fanlarni birlashtiramiz
        fanlar = set(q["fan"] for q in ordered)
        subject_name = ", ".join(fanlar) if len(fanlar) > 1 else list(fanlar)[0]
        
        return [SubjectBlock(
            start=first["tartib"],
            end=last["tartib"],
            subject=subject_name,
            point=first["ball"]
        )]
    
    elif total <= 60:
        # 2 ta blok: 1-30 va 31-60
        blocks = []
        
        # 1-blok (1-30 savollar)
        first_half = [q for q in ordered if q["tartib"] <= 30]
        if first_half:
            first = first_half[0]
            last = first_half[-1]
            fanlar = set(q["fan"] for q in first_half)
            subject_name = ", ".join(fanlar) if len(fanlar) > 1 else list(fanlar)[0]
            blocks.append(SubjectBlock(
                start=first["tartib"],
                end=last["tartib"],
                subject=subject_name,
                point=first["ball"]
            ))
        
        # 2-blok (31-60 savollar)
        second_half = [q for q in ordered if q["tartib"] > 30]
        if second_half:
            first = second_half[0]
            last = second_half[-1]
            fanlar = set(q["fan"] for q in second_half)
            subject_name = ", ".join(fanlar) if len(fanlar) > 1 else list(fanlar)[0]
            blocks.append(SubjectBlock(
                start=first["tartib"],
                end=last["tartib"],
                subject=subject_name,
                point=first["ball"]
            ))
        
        return blocks
    
    else:
        # 3 ta blok: 1-30, 31-60, 61-90
        blocks = []
        
        # 1-blok (1-30)
        part1 = [q for q in ordered if q["tartib"] <= 30]
        if part1:
            first = part1[0]
            last = part1[-1]
            fanlar = set(q["fan"] for q in part1)
            subject_name = ", ".join(fanlar) if len(fanlar) > 1 else list(fanlar)[0]
            blocks.append(SubjectBlock(
                start=first["tartib"],
                end=last["tartib"],
                subject=subject_name,
                point=first["ball"]
            ))
        
        # 2-blok (31-60)
        part2 = [q for q in ordered if 31 <= q["tartib"] <= 60]
        if part2:
            first = part2[0]
            last = part2[-1]
            fanlar = set(q["fan"] for q in part2)
            subject_name = ", ".join(fanlar) if len(fanlar) > 1 else list(fanlar)[0]
            blocks.append(SubjectBlock(
                start=first["tartib"],
                end=last["tartib"],
                subject=subject_name,
                point=first["ball"]
            ))
        
        # 3-blok (61-90)
        part3 = [q for q in ordered if q["tartib"] > 60]
        if part3:
            first = part3[0]
            last = part3[-1]
            fanlar = set(q["fan"] for q in part3)
            subject_name = ", ".join(fanlar) if len(fanlar) > 1 else list(fanlar)[0]
            blocks.append(SubjectBlock(
                start=first["tartib"],
                end=last["tartib"],
                subject=subject_name,
                point=first["ball"]
            ))
        
        return blocks


# ============================================================
# ASOSIY GENERATSIYA FUNKSIYASI
# ============================================================

def generate_exam_from_excel(
    excel_path: str,
    output_dir: str = "./generated_exam",
    group_name: str = TEST_GROUP_NAME,
    students: List[Dict] = None,
):
    """
    Excel fayldan imtihon generatsiya qiladi.
    """
    
    if students is None:
        students = TEST_STUDENTS
    
    # 1. Savollarni o'qish
    print("📖 Savollar o'qilmoqda...")
    questions = read_questions_from_excel(excel_path)
    print(f"✅ {len(questions)} ta savol o'qildi")
    
    # Savollar sonini chiqarish
    print("\n📊 Savollar statistikasi:")
    fanlar = {}
    for q in questions:
        fanlar[q['fan']] = fanlar.get(q['fan'], 0) + 1
    for fan, count in fanlar.items():
        print(f"   {fan}: {count} ta")
    
    # Ball statistikasi
    ballar = {}
    for q in questions:
        ballar[q['ball']] = ballar.get(q['ball'], 0) + 1
    print("\n📊 Ball statistikasi:")
    for ball, count in sorted(ballar.items()):
        print(f"   {ball} ball: {count} ta")
    
    # 2. Savollar sonini tekshirish
    total_questions = len(questions)
    if total_questions not in [30, 60, 90]:
        print(f"⚠️  Savollar soni: {total_questions} (30, 60 yoki 90 bo'lishi kerak)")
    
    # 3. Test to'plami ma'lumotlari
    test_set_name = f"Test {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    exam_code = _generate_exam_code()
    
    # 4. Fan bloklarini yaratish
    subject_blocks = _build_subject_blocks(questions)
    
    # Bloklar haqida ma'lumot
    print("\n📋 Fan bloklari:")
    for i, block in enumerate(subject_blocks, 1):
        print(f"   {i}-blok: {block.start}-{block.end}, {block.subject}, {block.point} ball")
    
    # 5. SheetExam yaratish
    sheet_exam = SheetExam(
        exam_id=exam_code,
        exam_name=test_set_name,
        total_questions=total_questions,
        subjects=subject_blocks,
    )
    
    # 6. Output papkalarini yaratish
    output_root = Path(output_dir)
    savollar_dir = output_root / "Savollar"
    javoblar_dir = output_root / "Javoblar_varaqasi"
    savollar_dir.mkdir(parents=True, exist_ok=True)
    javoblar_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📁 Output papkasi: {output_root}")
    print(f"📚 Savollar: {savollar_dir}")
    print(f"📋 Javoblar varaqasi: {javoblar_dir}")
    
    # 7. Har bir o'quvchi uchun generatsiya
    print("\n🔄 Generatsiya boshlandi...")
    
    exam_students = []
    
    for student_data in students:
        # Booklet ID
        booklet_id = _generate_booklet_id()
        
        # Savollarni randomizatsiya qilish
        seed = f"{exam_code}-{booklet_id}"
        rendered_questions, answer_key = build_shuffled_booklet(questions, seed=seed)
        
        # Student ma'lumotlari
        sheet_student = SheetStudent(
            id=student_data["id"],
            first_name=student_data["first_name"],
            last_name=student_data["last_name"],
            father_name=student_data.get("middle_name", ""),
            group_name=group_name,
        )
        
        sheet_booklet = SheetBooklet(
            booklet_id=booklet_id,
            exam_id=exam_code,
            student_id=student_data["id"],
        )
        
        # Fayl nomlari
        safe_name = f"{student_data['last_name']}_{student_data['first_name']}".replace(" ", "_")
        booklet_path = savollar_dir / f"{safe_name}_{booklet_id}_Savol.pdf"
        sheet_path = javoblar_dir / f"{safe_name}_{booklet_id}_Javoblar.pdf"
        
        # Savollar kitobini generatsiya qilish
        render_booklet_pdf(
            student={"full_name": sheet_student.full_name, "group_name": group_name},
            exam_id=exam_code,
            booklet_id=booklet_id,
            rendered_questions=rendered_questions,
            output_path=str(booklet_path),
        )
        
        # Javoblar varaqasini generatsiya qilish
        generate_answer_sheet(
            output_path=str(sheet_path),
            student=sheet_student,
            exam=sheet_exam,
            booklet=sheet_booklet,
        )
        
        exam_students.append({
            "student_id": student_data["id"],
            "booklet_id": booklet_id,
            "booklet_path": str(booklet_path),
            "answer_sheet_path": str(sheet_path),
            "answer_key": answer_key,
        })
        
        print(f"  ✅ {student_data['first_name']} {student_data['last_name']} - {booklet_id}")
    
    # 8. ZIP arxiv yaratish
    zip_name = f"{group_name}_{test_set_name}.zip".replace(" ", "_").replace("/", "_").replace(":", "-")
    zip_path = output_root / zip_name
    
    print(f"\n📦 ZIP arxiv yaratilmoqda: {zip_name}")
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in savollar_dir.glob("*.pdf"):
            zf.write(f, arcname=f"Savollar/{f.name}")
        for f in javoblar_dir.glob("*.pdf"):
            zf.write(f, arcname=f"Javoblar_varaqasi/{f.name}")
    
    # 9. Natijalar
    print("\n" + "=" * 60)
    print("✅ GENERATSIYA TUGADI!")
    print("=" * 60)
    print(f"\n📁 Natijalar: {output_root}")
    print(f"📦 ZIP: {zip_path}")
    print(f"📚 Savollar soni: {total_questions}")
    print(f"👥 O'quvchilar soni: {len(students)}")
    print(f"📋 Fan bloklari soni: {len(subject_blocks)}")
    for i, block in enumerate(subject_blocks, 1):
        print(f"   {i}-ustun: {block.start}-{block.end}, {block.subject}, {block.point} ball")
    
    # 10. Answer key ni ko'rsatish
    print("\n📝 ANSWER KEY (1-o'quvchi uchun):")
    print("-" * 40)
    first_student = exam_students[0]
    answer_key = json.loads(first_student["answer_key"]) if isinstance(first_student["answer_key"], str) else first_student["answer_key"]
    
    # 10 tadan ko'p bo'lsa, faqat 10 tasini ko'rsatamiz
    show_count = min(10, len(answer_key))
    for i, (q, ans) in enumerate(list(answer_key.items())[:show_count], 1):
        print(f"  {i:3d} -> {ans}")
    
    if len(answer_key) > 10:
        print(f"  ... va yana {len(answer_key) - 10} ta")


    print(f"\n🔍 DEBUG: subject_blocks = {len(subject_blocks)} ta")
    for i, block in enumerate(subject_blocks):
        print(f"   {i}: {block.start}-{block.end} {block.subject} {block.point}")

    print(f"🔍 DEBUG: total_questions = {total_questions}")
    print(f"🔍 DEBUG: columns = {len(subject_blocks)} ta ustun")
    
    return {
        "exam_code": exam_code,
        "output_dir": str(output_root),
        "zip_path": str(zip_path),
        "total_questions": total_questions,
        "students_count": len(students),
        "exam_students": exam_students,
        "subject_blocks": subject_blocks,
    }


# ============================================================
# SAVOLLAR SHABLONI YARATISH
# ============================================================

def create_sample_excel(output_path: str = "savollar_shabloni.xlsx"):
    """
    Namuna Excel fayl yaratadi (sizning formatda).
    """
    
    sample_data = {
        'T/r': list(range(1, 31)),
        'Fan': ['Majburiy fanlar'] * 10 + ['Matematika'] * 10 + ['Ingliz tili'] * 10,
        'Savol': [
            f"{i}-savol: O'zbekiston Respublikasi davlat mustaqilligini qaysi sanada e'lon qildi?" 
            if i == 1 else f"Test savoli {i}"
            for i in range(1, 31)
        ],
        'A': ['Variant A'] * 30,
        'B': ['Variant B'] * 30,
        'C': ['Variant C'] * 30,
        'D': ['Variant D'] * 30,
        "To'g'ri javob": ['B'] * 30,
        'Ball': [1.1] * 10 + [2.1] * 10 + [3.1] * 10,
    }
    
    df = pd.DataFrame(sample_data)
    df.to_excel(output_path, index=False)
    print(f"✅ Namuna Excel fayl yaratildi: {output_path}")
    print("\n📝 Excel format:")
    print("   T/r | Fan | Savol | A | B | C | D | To'g'ri javob | Ball")
    print("\n💡 Eslatma: 30, 60 yoki 90 ta savol bo'lishi mumkin.")
    print("   Namuna 30 ta savol (3 xil fan):")
    print("   - 1-10: Majburiy fanlar (1.1 ball)")
    print("   - 11-20: Matematika (2.1 ball)")
    print("   - 21-30: Ingliz tili (3.1 ball)")

    


# ============================================================
# MAIN
# ============================================================

def main():
    """Asosiy test funksiyasi"""
    
    print("\n" + "=" * 60)
    print("🏫 IMTIHON GENERATSIYASI TEST")
    print("=" * 60)
    print("\n📋 QOIDALAR:")
    print("   - 30 ta savol → HAMMASI 1-ustunda")
    print("   - 60 ta savol → 1.1 ball → 1-ustun, 2.1 ball → 2-ustun")
    print("   - 90 ta savol → 1.1 ball → 1-ustun, 2.1 ball → 2-ustun, 3.1 ball → 3-ustun")
    
    # 1. Excel faylni tekshirish
    excel_file = "savollar_shabloni.xlsx"
    
    if not os.path.exists(excel_file):
        print(f"\n⚠️  Excel fayl topilmadi: {excel_file}")
        print("📝 Namuna Excel fayl yaratilmoqda...")
        create_sample_excel(excel_file)
        print(f"\n✅ {excel_file} yaratildi!")
        print("📝 Iltimos, faylni o'zgartiring va qayta ishga tushiring.")
        return
    
    # 2. Generatsiya qilish
    try:
        result = generate_exam_from_excel(
            excel_path=excel_file,
            output_dir="./generated_exam",
            group_name=TEST_GROUP_NAME,
            students=TEST_STUDENTS,
        )
        
        print("\n" + "=" * 60)
        print("🎉 HAMMA ISHLAR TUGADI!")
        print("=" * 60)
        print(f"\n📦 ZIP fayl: {result['zip_path']}")
        print("📂 Papkani oching va natijalarni ko'ring.")
        
    except Exception as e:
        print(f"\n❌ XATOLIK: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# ISHGA TUSHIRISH
# ============================================================

if __name__ == "__main__":
    # Pandas tekshirish
    try:
        import pandas
    except ImportError:
        print("❌ Pandas o'rnatilmagan!")
        print("O'rnatish: pip install pandas openpyxl")
        sys.exit(1)
    
    main()


