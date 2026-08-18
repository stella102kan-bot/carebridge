import sqlite3
import os
import psycopg


# ========================================
# 1. 連接 SQLite
# ========================================

sqlite_conn = sqlite3.connect("carebridge.db")
sqlite_cursor = sqlite_conn.cursor()

print("SQLite 連線成功")


# ========================================
# 2. 取得 PostgreSQL DATABASE_URL
# ========================================

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "找不到 DATABASE_URL，請先設定環境變數。"
    )


# ========================================
# 3. 連接 PostgreSQL
# ========================================

pg_conn = psycopg.connect(DATABASE_URL)
pg_cursor = pg_conn.cursor()

print("PostgreSQL 連線成功")


# ========================================
# 4. 建立 doctors
# ========================================

pg_cursor.execute("""
CREATE TABLE IF NOT EXISTS doctors (
    doctor_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    username TEXT NOT NULL,
    password TEXT NOT NULL
)
""")


# ========================================
# 5. 建立 patients
# ========================================

pg_cursor.execute("""
CREATE TABLE IF NOT EXISTS patients (
    patient_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    birth_date TEXT,
    gender TEXT,
    phone TEXT,
    disease TEXT,
    allergy TEXT,
    medication TEXT,
    id_number TEXT,
    family_history TEXT
)
""")


# ========================================
# 6. 建立 visits
# ========================================

pg_cursor.execute("""
CREATE TABLE IF NOT EXISTS visits (
    visit_id INTEGER PRIMARY KEY,
    patient_id TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    status TEXT DEFAULT '已預約',
    chief_complaint TEXT,
    appointment_number INTEGER,
    appointment_time TEXT,
    checked_in_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    diagnosis TEXT,
    prescription TEXT,
    ai_summary TEXT
)
""")


print("PostgreSQL 資料表建立完成")


# ========================================
# 7. 搬移 doctors
# ========================================

sqlite_cursor.execute("""
SELECT
    doctor_id,
    name,
    username,
    password
FROM doctors
""")

doctors = sqlite_cursor.fetchall()

for doctor in doctors:

    pg_cursor.execute("""
        INSERT INTO doctors (
            doctor_id,
            name,
            username,
            password
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (doctor_id)
        DO UPDATE SET
            name = EXCLUDED.name,
            username = EXCLUDED.username,
            password = EXCLUDED.password
    """, doctor)


print(f"doctors 搬移完成：{len(doctors)} 筆")


# ========================================
# 8. 搬移 patients
# ========================================

sqlite_cursor.execute("""
SELECT
    patient_id,
    name,
    birth_date,
    gender,
    phone,
    disease,
    allergy,
    medication,
    id_number,
    family_history
FROM patients
""")

patients = sqlite_cursor.fetchall()

for patient in patients:

    pg_cursor.execute("""
        INSERT INTO patients (
            patient_id,
            name,
            birth_date,
            gender,
            phone,
            disease,
            allergy,
            medication,
            id_number,
            family_history
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        ON CONFLICT (patient_id)
        DO UPDATE SET
            name = EXCLUDED.name,
            birth_date = EXCLUDED.birth_date,
            gender = EXCLUDED.gender,
            phone = EXCLUDED.phone,
            disease = EXCLUDED.disease,
            allergy = EXCLUDED.allergy,
            medication = EXCLUDED.medication,
            id_number = EXCLUDED.id_number,
            family_history = EXCLUDED.family_history
    """, patient)


print(f"patients 搬移完成：{len(patients)} 筆")


# ========================================
# 9. 搬移 visits
# ========================================

sqlite_cursor.execute("""
SELECT
    visit_id,
    patient_id,
    visit_date,
    status,
    chief_complaint,
    appointment_number,
    appointment_time,
    checked_in_at,
    started_at,
    completed_at,
    diagnosis,
    prescription,
    ai_summary
FROM visits
""")

visits = sqlite_cursor.fetchall()

for visit in visits:

    pg_cursor.execute("""
        INSERT INTO visits (
            visit_id,
            patient_id,
            visit_date,
            status,
            chief_complaint,
            appointment_number,
            appointment_time,
            checked_in_at,
            started_at,
            completed_at,
            diagnosis,
            prescription,
            ai_summary
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (visit_id)
        DO UPDATE SET
            patient_id = EXCLUDED.patient_id,
            visit_date = EXCLUDED.visit_date,
            status = EXCLUDED.status,
            chief_complaint = EXCLUDED.chief_complaint,
            appointment_number = EXCLUDED.appointment_number,
            appointment_time = EXCLUDED.appointment_time,
            checked_in_at = EXCLUDED.checked_in_at,
            started_at = EXCLUDED.started_at,
            completed_at = EXCLUDED.completed_at,
            diagnosis = EXCLUDED.diagnosis,
            prescription = EXCLUDED.prescription,
            ai_summary = EXCLUDED.ai_summary
    """, visit)


print(f"visits 搬移完成：{len(visits)} 筆")


# ========================================
# 10. 提交
# ========================================

pg_conn.commit()

print()
print("========================================")
print("SQLite → PostgreSQL 搬移完成！")
print("========================================")


# ========================================
# 11. 驗證 PostgreSQL 筆數
# ========================================

for table in ["doctors", "patients", "visits"]:

    pg_cursor.execute(
        f"SELECT COUNT(*) FROM {table}"
    )

    count = pg_cursor.fetchone()[0]

    print(f"{table}: {count} 筆")


# ========================================
# 12. 關閉
# ========================================

sqlite_conn.close()
pg_conn.close()

print()
print("連線已關閉")