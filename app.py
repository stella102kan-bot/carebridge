#from urllib import response
from flask import Flask, render_template, request, session, redirect
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote
import uuid
import sqlite3
import requests
import json
import os
import psycopg
from math import radians, sin, cos, sqrt, atan2


app = Flask(__name__)
app.secret_key = "carebridge-demo-secret"

def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        return psycopg.connect(database_url)

    return sqlite3.connect("carebridge.db")

def get_db():
    return psycopg.connect(
        os.environ["DATABASE_URL"]
    )

@app.route("/test-db")
def test_db():

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT 1")

        result = cursor.fetchone()

        cursor.close()
        conn.close()

        return f"PostgreSQL 連線成功！結果：{result}"

    except Exception as e:

        return f"""
        <h1>PostgreSQL 連線失敗</h1>
        <pre>{e}</pre>
        """

def build_chronic_condition_fhir(
    patient_fhir_id,
    patient_id,
    disease
):
    return {
        "resourceType": "Condition",
        "identifier": [
            {
                "system": "https://carebridge.example/chronic-condition",
                "value": patient_id
            }
        ],
        "subject": {
            "reference": f"Patient/{patient_fhir_id}"
        },
        "code": {
            "text": disease
        }
    }

def build_allergy_fhir(fhir_patient_id, patient_id, allergy):
    return {
        "resourceType": "AllergyIntolerance",

        "identifier": [
            {
                "system": "https://carebridge.example/patient-id",
                "value": patient_id + "-allergy"
            }
        ],

        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": "active"
                }
            ]
        },
        "patient": {
            "reference": f"Patient/{fhir_patient_id}"
        },
        "code": {
            "text": allergy
        }
    }

def build_medication_fhir(fhir_patient_id, patient_id, medication):
    return {
        "resourceType": "MedicationStatement",

        "identifier": [
            {
                "system": "https://carebridge.example/patient-id",
                "value": patient_id + "-medication"
            }
        ],

        "status": "active",
        "subject": {
            "reference": f"Patient/{fhir_patient_id}"
        },
        "medicationCodeableConcept": {
            "text": medication
        }
    }

def build_family_history_fhir(fhir_patient_id, patient_id, family_history):
    return {
        "resourceType": "FamilyMemberHistory",

        "identifier": [
            {
                "system": "https://carebridge.example/patient-id",
                "value": patient_id + "-family-history"
            }
        ],

        "status": "completed",

        "patient": {
            "reference": f"Patient/{fhir_patient_id}"
        },

        "relationship": {
            "text": "家族"
        },

        "condition": [
            {
                "code": {
                    "text": family_history
                }
            }
        ]
    }

def build_condition_fhir(
    fhir_patient_id,
    patient_id,
    visit_id,
    diagnosis
):
    return {
        "resourceType": "Condition",

        "identifier": [
            {
                "system": "https://carebridge.example/condition",
                "value": patient_id + "-" + str(visit_id)
            }
        ],

        "subject": {
            "reference": f"Patient/{fhir_patient_id}"
        },

        "code": {
            "text": diagnosis
        }
    }

def build_patient_fhir(patient):
    return {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "https://carebridge.example/patient-id",
                "value": patient[0]
            }
        ],
        "name": [
            {
                "text": patient[1]
            }
        ],
        "gender": patient[3],
        "birthDate": patient[2],
        "telecom": [
            {
                "system": "phone",
                "value": patient[4]
            }
        ]
    }

def build_encounter_fhir(
    fhir_patient_id,
    patient_id,
    visit_id,
    visit_date,
    chief_complaint,
    diagnosis,
    prescription,
    status
):
    return {
        "resourceType": "Encounter",

        "identifier": [
            {
                "system": "https://carebridge.example/encounter",
                "value": patient_id + "-" + str(visit_id)
            }
        ],

        "status": status,

        "class": {
            "system":
            "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory"
        },

        "subject": {
            "reference":
            f"Patient/{fhir_patient_id}"
        },

        "period": {
            "start": visit_date,
            "end": visit_date
        },

        "reasonCode": [
            {
                "text": chief_complaint
            }
        ]
    }

def build_medication_request_fhir(
    patient_fhir_id,
    patient_id,
    visit_id,
    prescription
):
    return {
        "resourceType": "MedicationRequest",
        "identifier": [
            {
                "system": "https://carebridge.example/medication-request",
                "value": patient_id + "-" + str(visit_id)
            }
        ],
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "text": prescription
        },
        "subject": {
            "reference": f"Patient/{patient_fhir_id}"
        }
    }

def upload_or_update_resource(resource_type, resource, identifier_system, identifier_value):
    """
    若 Resource 已存在就更新，不存在就建立
    """

    # 搜尋 Resource
    search_url = (
        f"https://hapi.fhir.org/baseR4/{resource_type}"
        f"?identifier={identifier_system}|{identifier_value}"
    )

    search_response = requests.get(
        search_url,
        headers={"Accept": "application/fhir+json"},
        timeout=60
    )

    if search_response.status_code != 200:
        return None, search_response

    result = search_response.json()

    # 已存在 -> PUT 更新
    if result.get("total", 0) > 0:
            
        resource_id = result["entry"][0]["resource"]["id"]

        # PUT 一定要有 id
        resource["id"] = resource_id

        response = requests.put(
            f"https://hapi.fhir.org/baseR4/{resource_type}/{resource_id}",
            json=resource,
            headers={
                "Content-Type": "application/fhir+json"
            },
            timeout=60
        )

        print("PUT 狀態碼：", response.status_code)
        print("PUT 回傳內容：")
        print(response.text)

        return resource_id, response
    
    # 不存在 -> POST 建立
    else:

        resource.pop("id", None)

        response = requests.post(
            f"https://hapi.fhir.org/baseR4/{resource_type}",
            json=resource,
            headers={
                "Content-Type": "application/fhir+json"
            },
            timeout=60
        )

        print("POST 狀態碼：", response.status_code)
        print("POST 回傳內容：", response.text)

        if response.status_code in [200, 201]:
            resource_id = response.json()["id"]
            return resource_id, response

        return None, response

def init_db():

    conn = get_db_connection()
    cursor = conn.cursor()

    # =========================
    # patients
    # =========================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            birth_date TEXT,
            gender TEXT,
            phone TEXT,
            disease TEXT,
            allergy TEXT,
            medication TEXT,
            id_number TEXT UNIQUE,
            family_history TEXT
        )
    """)

    # =========================
    # visits
    # =========================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            visit_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            patient_id TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '已預約',
            chief_complaint TEXT,
            appointment_number INTEGER,
            appointment_time TEXT,
            checked_in_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            diagnosis TEXT,
            prescription TEXT,
            facility_id INTEGER,
            FOREIGN KEY (patient_id)
                REFERENCES patients(patient_id)
        )
    """)

    # 確保既有 PostgreSQL 的 visit_id 具有自動編號
    if os.environ.get("DATABASE_URL"):
        cursor.execute("""
            SELECT is_identity
            FROM information_schema.columns
            WHERE table_name = 'visits'
            AND column_name = 'visit_id'
        """)

        result = cursor.fetchone()

        if result and result[0] == "NO":
            cursor.execute("""
                ALTER TABLE visits
                ALTER COLUMN visit_id
                ADD GENERATED BY DEFAULT AS IDENTITY
            """)

            cursor.execute("""
                SELECT setval(
                    pg_get_serial_sequence('visits', 'visit_id'),
                    COALESCE((SELECT MAX(visit_id) FROM visits), 0) + 1,
                    false
                )
            """)

        if os.environ.get("DATABASE_URL"):
            cursor.execute("""
                SELECT COALESCE(MAX(visit_id), 0)
                FROM visits
            """)

            max_visit_id = cursor.fetchone()[0]
            print("目前最大的 visit_id：", max_visit_id)

    # =========================
    # doctors
    # =========================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            doctor_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # =========================
    # 建立測試醫師帳號
    # =========================

    cursor.execute("""
        INSERT INTO doctors (
            doctor_id,
            name,
            username,
            password
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (doctor_id) DO NOTHING
    """, (
        1,
        "慧慧醫師",
        "doctor",
        "1234"
    ))

    # =========================
    # medical_facilities
    # =========================
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medical_facilities (
            facility_id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            facility_type TEXT NOT NULL,
            address TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            specialties TEXT,
            average_wait_minutes INTEGER DEFAULT 0,
            current_waiting_count INTEGER DEFAULT 0,
            available_slots INTEGER DEFAULT 0,
            daily_capacity INTEGER DEFAULT 20
        )
    """)

    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'medical_facilities'
        AND column_name = 'daily_capacity'
    """)

    daily_capacity_column = cursor.fetchone()

    if not daily_capacity_column:
        cursor.execute("""
            ALTER TABLE medical_facilities
            ADD COLUMN daily_capacity INTEGER DEFAULT 20
        """)
    
    # =========================
    # 建立測試醫療院所
    # =========================

    test_facilities = [

        (
            "CareBridge 測試診所",
            "診所",
            "高雄市測試地址",
            22.6273,
            120.3014,
            "家醫科,內科",
            15,
            20
        ),

        (
            "CareBridge 第二醫院",
            "醫院",
            "高雄市第二測試地址",
            22.6300,
            120.3050,
            "內科,外科",
            25,
            30
        ),

        (
            "CareBridge 第三醫院",
            "醫院",
            "高雄市第三測試地址",
            22.6200,
            120.2950,
            "家醫科,兒科",
            20,
            25
        )
    ]


    for facility in test_facilities:

        cursor.execute("""
            SELECT facility_id
            FROM medical_facilities
            WHERE name = %s
            LIMIT 1
        """, (facility[0],))

        existing_facility = cursor.fetchone()

        if not existing_facility:

            cursor.execute("""
                INSERT INTO medical_facilities
                (
                    name,
                    facility_type,
                    address,
                    latitude,
                    longitude,
                    specialties,
                    average_wait_minutes,
                    daily_capacity
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, facility)


    # =========================
    # 確保 visits 有 facility_id
    # =========================

    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'visits'
        AND column_name = 'facility_id'
    """)

    facility_column = cursor.fetchone()

    if not facility_column:

        cursor.execute("""
            ALTER TABLE visits
            ADD COLUMN facility_id INTEGER
        """)


    conn.commit()
    conn.close()

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    計算兩個經緯度座標之間的距離
    回傳單位：公里
    """

    R = 6371.0

    lat1 = radians(lat1)
    lon1 = radians(lon1)
    lat2 = radians(lat2)
    lon2 = radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c

# 首頁
@app.route("/")
def home():
    return render_template("index.html")


# 醫生端
@app.route("/doctor")
def doctor():
    # 已經登入醫生，直接進入醫生首頁
    if "doctor_id" in session:
        return redirect("/doctor-home")

    # 尚未登入，顯示醫生登入頁
    return render_template("doctor-login.html")

@app.route("/doctor-login", methods=["POST"])
def doctor_login():

    username = request.form.get("username")
    password = request.form.get("password")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT doctor_id, name
        FROM doctors
        WHERE username = %s AND password = %s
    """, (username, password))

    doctor = cursor.fetchone()
    conn.close()

    if doctor:
        session["doctor_id"] = doctor[0]
        session["doctor_name"] = doctor[1]

        return redirect("/doctor-home")

    return """
    <h1>登入失敗</h1>
    <p>帳號或密碼錯誤。</p>

    <button onclick="location.href='/doctor'">
        返回醫生登入
    </button>
    """

@app.route("/doctor-home")
def doctor_home():

    if "doctor_id" not in session:
        return redirect("/doctor")

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 今日待處理患者
    cursor.execute("""
        SELECT
            visits.visit_id,
            patients.name,
            patients.patient_id,
            visits.status,
            visits.appointment_number,
            visits.appointment_time
        FROM visits
        JOIN patients
            ON visits.patient_id = patients.patient_id
        WHERE visits.visit_date = %s
        AND visits.status IN ('已報到', '已預約', '看診中')
        ORDER BY
            CASE
                WHEN visits.status = '已報到' THEN 0
                WHEN visits.status = '看診中' THEN 1
                WHEN visits.status = '已預約' THEN 2
                ELSE 3
            END,
            visits.appointment_number ASC
    """, (today,))

    waiting_patients = cursor.fetchall()

    # 今日已完成患者
    cursor.execute("""
        SELECT
            visits.visit_id,
            patients.name,
            patients.patient_id,
            visits.appointment_number,
            visits.appointment_time,
            visits.completed_at
        FROM visits
        JOIN patients
            ON visits.patient_id = patients.patient_id
        WHERE visits.visit_date = %s
        AND visits.status = '已完成'
        ORDER BY visits.completed_at DESC
    """, (today,))

    completed_patients = cursor.fetchall()

    conn.close()

    return render_template(
        "doctor.html",
        doctor_name=session["doctor_name"],
        waiting_patients=waiting_patients,
        completed_patients=completed_patients
    )

@app.route("/doctor-patient/<patient_id>")
def doctor_patient(patient_id):

    if "doctor_id" not in session:
        return redirect("/doctor")

    # -------------------------
    # 先取得病患基本資料
    # -------------------------

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            patients.patient_id,
            patients.name,
            patients.birth_date,
            patients.gender,
            patients.phone,
            patients.disease,
            patients.allergy,
            patients.medication,
            patients.family_history,
            visits.chief_complaint,
            visits.status
        FROM patients
        JOIN visits
            ON patients.patient_id = visits.patient_id
        WHERE patients.patient_id = %s
        ORDER BY visits.visit_id DESC
        LIMIT 1
    """, (patient_id,))

    patient = cursor.fetchone()

    cursor.execute("""
        SELECT
            visit_id,
            visit_date,
            appointment_time,
            chief_complaint,
            diagnosis,
            prescription,
            completed_at
        FROM visits
        WHERE patient_id = %s
        ORDER BY visit_date DESC, visit_id DESC
    """, (patient_id,))

    history = cursor.fetchall()

    print(history)

    conn.close()

    # -------------------------
    # 找不到病患
    # -------------------------
    if not patient:
        return """
        <h1>找不到病患</h1>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # -------------------------
    # 計算年齡
    # -------------------------
    from datetime import datetime

    age = "未提供"

    # 如果有出生日期，就計算年齡
    if patient[2]:

        birth = datetime.strptime(
            patient[2],
            "%Y-%m-%d"
        )

        today = datetime.today()

        age = (
            today.year
            - birth.year
            - (
                (today.month, today.day)
                < (birth.month, birth.day)
            )
        )

    # -------------------------
    # 從 FHIR Server 查詢 Condition
    # -------------------------

    condition_search_url = (
        "https://hapi.fhir.org/baseR4/Condition"
    )

    condition_response = requests.get(
        condition_search_url,
        params={
            "identifier":
            "https://carebridge.example/chronic-condition|"
            + patient_id
        },
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60
    )

    disease = "目前沒有 FHIR 慢性病資料"

    if condition_response.status_code == 200:

        condition_result = condition_response.json()

        if condition_result.get("total", 0) > 0:

            condition_resource = (
                condition_result["entry"][0]["resource"]
            )

            disease = (
                condition_resource
                .get("code", {})
                .get("text", "未提供")
            )

    # -------------------------
    # 顯示病患詳細資料
    # -------------------------

    history_html = "".join([
        f"""
        <div style="border:1px solid #ccc; padding:10px; margin-bottom:10px;">
            <p><strong>第 {len(history)-i} 次看診</strong></p>
            <p>日期：{visit[1]}</p>
            <p>時間：{visit[2]}</p>
            <button onclick="location.href='/hospital-prescription-detail/{visit[0]}'">
                查看詳細資料
            </button>
        </div>
        """
        for i, visit in enumerate(history)
    ])

    return f"""
    <h1>病患詳細資料</h1>

    <hr>

    <h2>{patient[1]}</h2>

    <p>
        <strong>Patient ID：</strong>
        {patient[0]}
    </p>

    <p>
        <strong>出生日期：</strong>
        {patient[2] or "未提供"}
    </p>

    <p>
        <strong>年齡：</strong>
        {age} 歲
    </p>

    <p>
        <strong>性別：</strong>
        {patient[3] or "未提供"}
    </p>

    <p>
        <strong>電話：</strong>
        {patient[4] or "未提供"}
    </p>

    <hr>

    <h3>長期健康資料</h3>

    <p>
        <strong>慢性病：</strong>
        {disease}
    </p>

    <p>
        <strong>過敏史：</strong>
        {patient[6] or "無資料"}
    </p>

    <p>
        <strong>目前用藥：</strong>
        {patient[7] or "無資料"}
    </p>

    <p>
        <strong>家族疾病史：</strong>
        {patient[8] or "無資料"}
    </p>

    <hr>

    <h3>本次就診</h3>

    <p>
        <strong>患者原始描述：</strong>
    </p>

    <p>
        {patient[9] or "未提供"}
    </p>

    <p>
        <strong>就診狀態：</strong>
        {patient[10] or "未提供"}
    </p>

    <hr>

    <h3>歷史就診紀錄</h3>

    {history_html}

    <hr>

    <button onclick="location.href='/doctor-fhir/{patient[0]}'">
        查看 FHIR 資料
    </button>

    <button onclick="location.href='/doctor-home'">
        回到醫生首頁
    </button>
    """

@app.route("/doctor-start/<int:visit_id>", methods=["POST"])
def doctor_start(visit_id):

    if "doctor_id" not in session:
        return redirect("/doctor")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 確認這筆就診存在
    cursor.execute("""
        SELECT status
        FROM visits
        WHERE visit_id = %s
    """, (visit_id,))

    visit = cursor.fetchone()

    if not visit:
        conn.close()
        return """
        <h1>找不到這筆就診資料</h1>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # 只有已報到才能開始看診
    if visit[0] != "已報到":
        conn.close()

        return """
        <h1>無法開始看診</h1>

        <p>患者目前尚未報到，無法開始看診。</p>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # 記錄真正開始看診的時間
    started_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute("""
        UPDATE visits
        SET status = '看診中',
            started_at = %s
        WHERE visit_id = %s
    """, (
        started_at,
        visit_id
    ))

    conn.commit()
    conn.close()

    return redirect(
        f"/doctor-consult/{visit_id}"
    )

@app.route("/doctor-consult/<int:visit_id>")
def doctor_consult(visit_id):

    if "doctor_id" not in session:
        return redirect("/doctor")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            visits.visit_id,
            patients.patient_id,
            patients.name,
            patients.birth_date,
            patients.gender,
            patients.phone,
            patients.disease,
            patients.allergy,
            patients.medication,
            patients.family_history,
            visits.chief_complaint,
            visits.status,
            visits.appointment_number
        FROM visits
        JOIN patients
            ON visits.patient_id = patients.patient_id
        WHERE visits.visit_id = %s
        LIMIT 1
    """, (visit_id,))

    visit = cursor.fetchone()

    conn.close()

    # -------------------------
    # 找不到就診資料
    # -------------------------

    if not visit:
        return """
        <h1>找不到就診資料</h1>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # -------------------------
    # 計算年齡
    # -------------------------

    age = "未提供"

    if visit[3]:
        birth = datetime.strptime(
            visit[3],
            "%Y-%m-%d"
        )

        today = datetime.today()

        age = (
            today.year
            - birth.year
            - (
                (today.month, today.day)
                < (birth.month, birth.day)
            )
        )

    # -------------------------
    # 確認目前狀態
    # -------------------------

    if visit[11] != "看診中":
        return """
        <h1>目前無法進入看診</h1>

        <p>患者目前不是看診中狀態。</p>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    return render_template(
        "doctor-consult.html",
        visit=visit,
        age=age
    )

@app.route("/doctor-complete/<int:visit_id>", methods=["POST"])
def doctor_complete(visit_id):

    if "doctor_id" not in session:
        return redirect("/doctor")

    diagnosis = request.form.get(
        "diagnosis",
        ""
    ).strip()

    prescription = request.form.get(
        "prescription",
        ""
    ).strip()

    if not diagnosis or not prescription:
        return """
        <h1>請填寫診斷結果與處方</h1>

        <button onclick="history.back()">
            回到看診頁
        </button>
        """

    completed_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # 改成 PostgreSQL / get_db_connection()
    conn = get_db_connection()
    cursor = conn.cursor()

    # -------------------------
    # 檢查這筆看診是否存在
    # -------------------------
    cursor.execute("""
        SELECT status
        FROM visits
        WHERE visit_id = %s
    """, (visit_id,))

    visit = cursor.fetchone()

    if not visit:
        conn.close()

        return """
        <h1>找不到這筆就診資料</h1>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # -------------------------
    # 確認目前狀態是「看診中」
    # -------------------------
    if visit[0] != "看診中":
        conn.close()

        return """
        <h1>無法完成看診</h1>

        <p>這筆就診目前不是看診中狀態。</p>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # -------------------------
    # 更新本次看診資料
    # -------------------------
    cursor.execute("""
        UPDATE visits
        SET
            diagnosis = %s,
            prescription = %s,
            completed_at = %s,
            status = '已完成'
        WHERE visit_id = %s
    """, (
        diagnosis,
        prescription,
        completed_at,
        visit_id
    ))

    # -------------------------
    # 取得本次就診資料
    # -------------------------
    cursor.execute("""
        SELECT
            patients.patient_id,
            patients.disease,
            visits.visit_date,
            visits.chief_complaint,
            visits.diagnosis,
            visits.prescription,
            visits.status
        FROM visits
        JOIN patients
            ON visits.patient_id = patients.patient_id
        WHERE visits.visit_id = %s
    """, (visit_id,))

    visit_info = cursor.fetchone()

    if not visit_info:
        conn.close()

        return """
        <h1>找不到患者資料</h1>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    patient_id = visit_info[0]
    chronic_disease = visit_info[1]
    visit_date = visit_info[2]
    chief_complaint = visit_info[3]
    diagnosis = visit_info[4]
    prescription = visit_info[5]

    # FHIR Encounter 使用 finished
    status = "finished"

    print("================================")
    print("Doctor complete")
    print("visit_id:", visit_id)
    print("patient_id:", patient_id)
    print("diagnosis:", diagnosis)
    print("prescription:", prescription)
    print("================================")

    # -------------------------
    # 查詢 FHIR Patient
    # -------------------------
    search_url = (
        "https://hapi.fhir.org/baseR4/Patient"
        "?identifier=https://carebridge.example/patient-id|"
        + patient_id
    )

    print("FHIR Patient search URL:", search_url)

    try:

        response = requests.get(
            search_url,
            headers={
                "Accept": "application/fhir+json"
            },
            timeout=30
        )

    except requests.RequestException as e:

        conn.close()

        print("FHIR Server connection error:", e)

        return f"""
        <h1>看診完成失敗</h1>

        <p>無法連線至 FHIR Server。</p>

        <p>錯誤原因：</p>

        <pre>{e}</pre>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # -------------------------
    # 檢查 FHIR Server 回應
    # -------------------------
    if response.status_code != 200:

        conn.close()

        print(
            "FHIR Server status code:",
            response.status_code
        )

        return f"""
        <h1>看診完成失敗</h1>

        <p>FHIR Server 回應錯誤。</p>

        <p>
            FHIR Server 回應狀態碼：
            {response.status_code}
        </p>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # -------------------------
    # 解析 FHIR Patient 搜尋結果
    # -------------------------
    result = response.json()

    print("================================")
    print("FHIR Patient search result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("FHIR Patient search total:", result.get("total"))
    print("FHIR Patient search URL:", search_url)
    print("================================")

    if result.get("total", 0) == 0:

        conn.close()

        return f"""
        <h1>看診完成失敗</h1>

        <p>找不到這位患者的 FHIR Patient 資料。</p>

        <p>
            CareBridge Patient ID：
            {patient_id}
        </p>

        <p>
            FHIR 搜尋網址：
            {search_url}
        </p>

        <p>
            FHIR 搜尋結果 total：
            {result.get("total")}
        </p>

        <pre>{json.dumps(result, indent=2, ensure_ascii=False)}</pre>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    # -------------------------
    # 取得 FHIR Patient ID
    # -------------------------
    fhir_patient_id = (
        result["entry"][0]["resource"]["id"]
    )

    print(
        "FHIR Patient ID:",
        fhir_patient_id
    )

    # -------------------------
    # 建立 Encounter
    # -------------------------
    encounter = build_encounter_fhir(
        fhir_patient_id,
        patient_id,
        visit_id,
        visit_date,
        chief_complaint,
        diagnosis,
        prescription,
        status
    )

    print("Encounter:")
    print(encounter)

    encounter_id, encounter_response = (
        upload_or_update_resource(
            "Encounter",
            encounter,
            "https://carebridge.example/encounter",
            patient_id + "-" + str(visit_id)
        )
    )

    print(
        "Encounter ID:",
        encounter_id
    )

    print(
        "Encounter 狀態碼:",
        encounter_response.status_code
    )

    # -------------------------
    # 建立本次診斷 Condition
    # -------------------------
    condition = build_condition_fhir(
        fhir_patient_id,
        patient_id,
        visit_id,
        diagnosis
    )

    condition_id, condition_response = (
        upload_or_update_resource(
            "Condition",
            condition,
            "https://carebridge.example/condition",
            patient_id + "-" + str(visit_id)
        )
    )

    print(
        "Condition ID:",
        condition_id
    )

    print(
        "Condition 狀態碼:",
        condition_response.status_code
    )

    # -------------------------
    # 上傳慢性病 Condition
    # -------------------------
    if chronic_disease:

        chronic_condition = (
            build_chronic_condition_fhir(
                fhir_patient_id,
                patient_id,
                chronic_disease
            )
        )

        (
            chronic_condition_id,
            chronic_condition_response
        ) = upload_or_update_resource(
            "Condition",
            chronic_condition,
            "https://carebridge.example/chronic-condition",
            patient_id
        )

        print(
            "Chronic Condition ID:",
            chronic_condition_id
        )

        print(
            "Chronic Condition 狀態碼:",
            chronic_condition_response.status_code
        )

    # -------------------------
    # 建立 MedicationRequest
    # -------------------------
    medication_request = (
        build_medication_request_fhir(
            fhir_patient_id,
            patient_id,
            visit_id,
            prescription
        )
    )

    (
        medication_request_id,
        medication_request_response
    ) = upload_or_update_resource(
        "MedicationRequest",
        medication_request,
        "https://carebridge.example/medication-request",
        patient_id + "-" + str(visit_id)
    )

    print(
        "MedicationRequest ID:",
        medication_request_id
    )

    print(
        "MedicationRequest 狀態碼:",
        medication_request_response.status_code
    )

    # -------------------------
    # 儲存資料
    # -------------------------
    conn.commit()
    conn.close()

    return """
    <h1>看診完成！</h1>

    <p>處方已成功傳送至醫院端。</p>

    <p>患者本次看診已完成。</p>

    <button onclick="location.href='/doctor-home'">
        回到醫生首頁
    </button>
    """

@app.route("/hospital-checkin", methods=["GET", "POST"])
def hospital_checkin():

    if "hospital_user" not in session:
        return redirect("/hospital-login")

    # GET：顯示報到頁
    if request.method == "GET":
        return render_template("hospital-checkin.html")

    id_number = request.form.get(
        "id_number",
        ""
    ).strip().upper()

    if not id_number:
        return """
        <h1>請輸入身分證字號</h1>

        <button onclick="location.href='/hospital-checkin'">
            返回
        </button>
        """

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            visits.visit_id,
            patients.name,
            patients.patient_id,
            patients.id_number,
            visits.appointment_number,
            visits.appointment_time,
            visits.chief_complaint,
            visits.status
        FROM visits
        JOIN patients
            ON visits.patient_id = patients.patient_id
        WHERE patients.id_number = %s
        AND visits.visit_date = %s
        AND visits.status = '已預約'
        ORDER BY visits.visit_id DESC
        LIMIT 1
    """, (
        id_number,
        today
    ))

    visit = cursor.fetchone()

    conn.close()

    if not visit:
        return """
        <h1>找不到今天的預約</h1>

        <p>
            請確認身分證字號是否正確，
            或確認今天是否有預約。
        </p>

        <button onclick="location.href='/hospital-checkin'">
            返回
        </button>
        """

    return render_template(
        "hospital-confirm.html",
        visit=visit,
        id_number=id_number
    )

@app.route("/hospital-checkin-confirm", methods=["POST"])
def hospital_checkin_confirm():

    if "hospital_user" not in session:
        return redirect("/hospital-login")

    id_number = request.form.get(
        "id_number",
        ""
    ).strip().upper()

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 找到今天這位患者的預約
    cursor.execute("""
        SELECT
            visits.visit_id,
            patients.name,
            patients.patient_id,
            visits.appointment_number,
            visits.appointment_time,
            visits.chief_complaint,
            visits.status
        FROM visits
        JOIN patients
            ON visits.patient_id = patients.patient_id
        WHERE patients.id_number = %s
        AND visits.visit_date = %s
        AND visits.status = '已預約'
        ORDER BY visits.visit_id DESC
        LIMIT 1
    """, (id_number, today))

    visit = cursor.fetchone()

    if not visit:
        conn.close()

        return """
        <h1>找不到可報到的預約</h1>

        <p>
            請確認身分證字號，或確認今天是否有預約。
        </p>

        <button onclick="location.href='/hospital-checkin'">
            返回報到
        </button>
        """

    visit_id = visit[0]
    appointment_number = visit[3]

    checked_in_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # 更新狀態
    cursor.execute("""
        UPDATE visits
        SET
            status = '已報到',
            checked_in_at = %s
        WHERE visit_id = %s
    """, (
        checked_in_at,
        visit_id
    ))

    conn.commit()

    # 計算前方已報到人數
    cursor.execute("""
        SELECT COUNT(*)
        FROM visits
        WHERE visit_date = %s
        AND status = '已報到'
        AND appointment_number < %s
    """, (
        today,
        appointment_number
    ))

    earlier_checked_in = cursor.fetchone()[0]

    # 正在看診的人
    cursor.execute("""
        SELECT COUNT(*)
        FROM visits
        WHERE visit_date = %s
        AND status = '看診中'
    """, (today,))

    consulting_count = cursor.fetchone()[0]

    queue_position = (
        earlier_checked_in
        + consulting_count
        + 1
    )

    waiting_ahead = queue_position - 1

    conn.close()

    return f"""
    <h1>報到完成！</h1>

    <hr>

    <h2>{visit[1]} 您好</h2>

    <p>
        <strong>預約號碼：</strong>
        {appointment_number}
    </p>

    <p>
        <strong>目前狀態：</strong>
        已報到
    </p>

    <p>
        <strong>前方等待人數：</strong>
        {waiting_ahead} 人
    </p>

    <p>
        <strong>目前候診順位：</strong>
        第 {queue_position} 位
    </p>

    <hr>

    <p>
        請耐心等待醫生叫號。
    </p>

    <button onclick="location.href='/hospital'">
        返回醫院工作平台
    </button>
    """

@app.route("/doctor-fhir/<patient_id>")
def doctor_fhir(patient_id):

    if "doctor_id" not in session:
        return redirect("/doctor")

    search_url = (
        "https://hapi.fhir.org/baseR4/Patient"
        "?identifier=https://carebridge.example/patient-id|"
        + patient_id
    )

    response = requests.get(
        search_url,
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60
    )

    if response.status_code != 200:
        return f"""
        <h1>FHIR 查詢失敗</h1>

        <p>HTTP Status Code：{response.status_code}</p>

        <pre>{response.text}</pre>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    result = response.json()

    if result.get("total", 0) == 0:
        return """
        <h1>找不到 FHIR 資料</h1>

        <p>FHIR Server 中沒有找到這位病患。</p>

        <button onclick="location.href='/doctor-home'">
            回到醫生首頁
        </button>
        """

    fhir_patient = result["entry"][0]["resource"]
    fhir_patient_id = fhir_patient["id"]

    # 查詢慢性病 Condition

    chronic_response = requests.get(
        "https://hapi.fhir.org/baseR4/Condition",
        params={
            "identifier":
            "https://carebridge.example/chronic-condition|" + patient_id
        },
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60
    )


    chronic_result = chronic_response.json()


    if chronic_result.get("total",0)>0:
        chronic_condition = (
            chronic_result["entry"][0]["resource"]
        )
    else:
        chronic_condition = None


    # 查詢 AllergyIntolerance
    allergy_response = requests.get(
        f"https://hapi.fhir.org/baseR4/AllergyIntolerance?patient=Patient/{fhir_patient_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60
    )

    allergy_result = allergy_response.json()

    if allergy_result.get("total", 0) > 0:
        allergy = allergy_result["entry"][0]["resource"]
    else:
        allergy = None


    # 查詢 MedicationStatement
    medication_response = requests.get(
        f"https://hapi.fhir.org/baseR4/MedicationStatement?patient=Patient/{fhir_patient_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60
    )

    medication_result = medication_response.json()

    if medication_result.get("total", 0) > 0:
        medication_statement = medication_result["entry"][0]["resource"]
    else:
        medication_statement = None


    # 查詢 FamilyMemberHistory
    family_response = requests.get(
        f"https://hapi.fhir.org/baseR4/FamilyMemberHistory?patient=Patient/{fhir_patient_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60
    )

    family_result = family_response.json()

    if family_result.get("total", 0) > 0:
        family_history = family_result["entry"][0]["resource"]
    else:
        family_history = None

    encounter_response = requests.get(
        "https://hapi.fhir.org/baseR4/Encounter",
        params={
            "subject": f"Patient/{fhir_patient_id}",
            "_count": 100,
            "_sort": "-date"
        },
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60
    )


    encounter_result = encounter_response.json()

    print("FHIR Encounter total:", encounter_result.get("total"))
    print("FHIR Encounter count:", len(encounter_result.get("entry", [])))

    encounters = []

    if encounter_result.get("total", 0) > 0:
        encounters = [
            entry["resource"]
            for entry in encounter_result["entry"]
        ]

    visit_records = []

    for encounter in encounters:

        encounter_identifier = encounter["identifier"][0]["value"]

        # 查詢這位病患所有 Condition
        condition_response = requests.get(
            "https://hapi.fhir.org/baseR4/Condition",
            params={
                "patient": fhir_patient_id
            },
            headers={
                "Accept": "application/fhir+json"
            },
            timeout=60
        )


        condition = None

        conditions = []

        if condition_response.status_code == 200:

            result = condition_response.json()

            if result.get("total", 0) > 0:

                conditions = [
                    e["resource"]
                    for e in result["entry"]
                ]


        # 找出本次看診的診斷 Condition
        for c in conditions:

            if (
                c.get("identifier")
                and
                c["identifier"][0]["system"]
                == "https://carebridge.example/condition"
                and
                c["identifier"][0]["value"]
                == encounter["identifier"][0]["value"]
            ):
                condition = c

        print("Condition search:")
        print(
            "https://carebridge.example/condition|"
            + encounter["identifier"][0]["value"]
        )

        print(condition_response.json())

        # 查詢同一次看診的 MedicationRequest（處方）
        medication_response = requests.get(
            "https://hapi.fhir.org/baseR4/MedicationRequest",
            params={
                "identifier":
                "https://carebridge.example/medication-request|"
                + encounter["identifier"][0]["value"]
            },
            headers={
                "Accept": "application/fhir+json"
            },
            timeout=60
        )

        medication_request = None
        if medication_response.status_code == 200:
            result = medication_response.json()
            if result.get("total", 0) > 0:
                medication_request = result["entry"][0]["resource"]

        visit_records.append({
            "encounter": encounter,
            "condition": condition,
            "medication_request": medication_request
        })

    visit_records_html = "".join([
        f"""
        <hr>

        <h3>Encounter</h3>
        <pre>{json.dumps(record["encounter"], ensure_ascii=False, indent=2)}</pre>

        <h3>Condition</h3>
        <pre>{json.dumps(record["condition"], ensure_ascii=False, indent=2)}</pre>

        <h3>MedicationRequest</h3>
        <pre>{json.dumps(record["medication_request"], ensure_ascii=False, indent=2)}</pre>
        """
        for record in visit_records
    ])

    return f"""
    <h1>FHIR Patient 資料</h1>

    <h2>Patient</h2>
    <pre>{json.dumps(fhir_patient, ensure_ascii=False, indent=2)}</pre>

    <h2>Condition（慢性病）</h2>
    <pre>{json.dumps(chronic_condition, ensure_ascii=False, indent=2)}</pre>

    <h2>AllergyIntolerance（過敏史）</h2>
    <pre>{json.dumps(allergy, ensure_ascii=False, indent=2)}</pre>

    <h2>MedicationStatement（長期用藥）</h2>
    <pre>{json.dumps(medication_statement, ensure_ascii=False, indent=2)}</pre>

    <h2>FamilyMemberHistory（家族疾病史）</h2>
    <pre>{json.dumps(family_history, ensure_ascii=False, indent=2)}</pre>

    <h2>所有就診紀錄</h2>

    {visit_records_html}

    <br>

    <button onclick="history.back()">
        回到病患詳情
    </button>

    <button onclick="location.href='/doctor-home'">
        回到醫生首頁
    </button>
    """

@app.route("/doctor-logout")
def doctor_logout():

    session.pop("doctor_id", None)
    session.pop("doctor_name", None)

    return redirect("/")

# 患者端
@app.route("/patient", methods=["GET", "POST"])
def patient():

    if request.method == "GET":
        return render_template("patient-login.html")

    id_number = request.form.get(
        "id_number",
        ""
    ).strip().upper()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            patient_id,
            name
        FROM patients
        WHERE id_number = %s
        LIMIT 1
    """, (id_number,))

    patient = cursor.fetchone()

    conn.close()

    if not patient:
        return """
        <h1>登入失敗</h1>

        <p>找不到此身分證字號，請確認是否已註冊。</p>

        <button onclick="location.href='/patient'">
            返回登入
        </button>
        """

    session["patient_id"] = patient[0]
    session["patient_name"] = patient[1]

    return redirect("/patient-home")

@app.route("/login", methods=["POST"])
def login():
    phone = request.form.get("phone")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT patient_id, name FROM patients WHERE phone = %s",
        (phone,)
    )

    patient = cursor.fetchone()
    conn.close()

    if patient:
        session["patient_id"] = patient[0]
        session["patient_name"] = patient[1]

        return redirect("/patient-home")

    return """
<h1>登入失敗</h1>
<p>找不到這個手機號碼，請確認是否註冊過。</p>

<button onclick="location.href='/patient'">
    返回登入
</button>

<button onclick="location.href='/register'">
    前往註冊
</button>
"""

@app.route("/patient-home")
def patient_home():

    if "patient_id" not in session:
        return redirect("/patient")

    patient_id = session["patient_id"]
    patient_name = session.get("patient_name", "患者")

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 取得今天最新的一筆預約
    cursor.execute("""
        SELECT
            appointment_number,
            appointment_time,
            status,
            chief_complaint,
            ai_summary
        FROM visits
        WHERE patient_id = %s
        AND visit_date = %s
        ORDER BY visit_id DESC
        LIMIT 1
    """, (patient_id, today))

    visit = cursor.fetchone()

    conn.close()

    # -------------------------
    # 顯示今日預約資訊
    # -------------------------

    appointment_info = ""

    if visit:

        appointment_info = f"""
        <hr>

        <h3>今日預約</h3>

        <p>
            <strong>預約號碼：</strong>
            {visit[0]}
        </p>

        <p>
            <strong>預約時間：</strong>
            {visit[1]}
        </p>

        <p>
            <strong>目前狀態：</strong>
            {visit[2]}
        </p>

        <p>
            <strong>本次症狀／就診原因：</strong>
            {visit[3] or "未提供"}
        </p>

        <br>

        <button onclick="location.href='/my-queue'">
            查看候診進度
        </button>
        """

    else:

        appointment_info = """
        <hr>

        <h3>今日尚無預約</h3>

        <p>您目前還沒有今天的看診預約。</p>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="zh-TW">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>CareBridge - 患者首頁</title>
    </head>

    <body>

        <h1>患者首頁</h1>

        <h2>歡迎回來，{patient_name}！</h2>

        <p>
            <strong>Patient ID：</strong>
            {patient_id}
        </p>

        <hr>

        <button onclick="location.href='/health-info'">
            我的健康資料
        </button>

        <br><br>

        <button onclick="location.href='/choose-facility'">
            我要看診
        </button>

        <br><br>

        {appointment_info}

        <hr>

        <h3>FHIR 資料</h3>

        <button onclick="location.href='/patient-fhir'">
            查看我的 FHIR 資料
        </button>

        <br><br>

        <form
            action="/send-fhir"
            method="POST"
            style="display:inline;"
        >
            <button type="submit">
                將資料送到 FHIR Server
            </button>
        </form>

        <br><br>

        <button onclick="location.href='/get-fhir'">
            從 FHIR Server 查詢我的資料
        </button>

        <hr>

        <button onclick="location.href='/logout'">
            登出
        </button>

    </body>

    </html>
    """

@app.route("/choose-facility")
def choose_facility():

    if "patient_id" not in session:
        return redirect("/patient")

    return """
    <!DOCTYPE html>
    <html lang="zh-TW">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>CareBridge - 看診方式</title>
    </head>

    <body>

        <h1>我要看診</h1>

        <p>
            請先告訴我們您是否已經有指定的醫療院所。
        </p>

        <hr>

        <h2>您有指定醫療院所嗎？</h2>

        <br>

        <button onclick="location.href='/specified-facility'">
            有，我有指定的醫院
        </button>

        <br><br>

        <button onclick="location.href='/visit'">
            沒有，請幫我推薦
        </button>

        <br><br>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>

    </body>

    </html>
    """

@app.route("/specified-facility")
def specified_facility():

    if "patient_id" not in session:
        return redirect("/patient")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            facility_id,
            name,
            facility_type,
            address,
            specialties
        FROM medical_facilities
        ORDER BY facility_id
    """)

    facilities = cursor.fetchall()

    conn.close()

    if not facilities:
        return """
        <h1>目前沒有可選擇的醫療院所</h1>

        <p>
            目前系統中沒有醫療院所資料。
        </p>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    facility_html = ""

    for facility in facilities:

        (
            facility_id,
            name,
            facility_type,
            address,
            specialties
        ) = facility

        facility_html += f"""
        <div>

            <h2>{name}</h2>

            <p>
                <strong>院所類型：</strong>
                {facility_type}
            </p>

            <p>
                <strong>地址：</strong>
                {address}
            </p>

            <p>
                <strong>提供科別：</strong>
                {specialties or "未提供"}
            </p>

            <button
                onclick="location.href='/visit?facility_id={facility_id}'"
            >
                選擇這間院所
            </button>

        </div>

        <hr>
        """

    return f"""
    <!DOCTYPE html>

    <html lang="zh-TW">

    <head>
        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width,
                     initial-scale=1.0"
        >

        <title>CareBridge - 選擇醫療院所</title>
    </head>

    <body>

        <h1>選擇指定醫療院所</h1>

        <p>
            請選擇您這次想前往的醫療院所。
        </p>

        <hr>

        {facility_html}

        <button onclick="location.href='/choose-facility'">
            返回
        </button>

        <br><br>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>

    </body>

    </html>
    """

@app.route("/visit", methods=["GET", "POST"])
def visit():

    if "patient_id" not in session:
        return redirect("/patient")

    patient_id = session["patient_id"]

    # =========================
    # GET：顯示症狀輸入頁
    # =========================

    if request.method == "GET":

        facility_id = request.args.get("facility_id")

        return render_template(
            "visit.html",
            facility_id=facility_id
        )

    # =========================
    # POST：取得資料
    # =========================

    chief_complaint = request.form.get(
        "chief_complaint",
        ""
    ).strip()

    facility_id = request.form.get(
        "facility_id"
    )

    # =========================
    # 檢查症狀
    # =========================

    if not chief_complaint:

        return """
        <h1>請輸入本次症狀</h1>

        <p>
            請告訴醫生這次到醫院的原因或目前症狀。
        </p>

        <button onclick="location.href='/visit'">
            返回
        </button>
        """

    # =========================
    # 日期與患者測試位置
    # =========================

    today = datetime.now(
        ZoneInfo("Asia/Taipei")
    ).strftime("%Y-%m-%d")

    patient_latitude = 22.6273
    patient_longitude = 120.3014

    # =========================
    # 建立資料庫連線
    # =========================

    conn = get_db_connection()
    cursor = conn.cursor()

    # =========================
    # 檢查今天是否已有預約
    # =========================

    cursor.execute("""
        SELECT visit_id
        FROM visits
        WHERE patient_id = %s
        AND visit_date = %s
        AND status IN ('已預約', '已報到', '看診中')
        ORDER BY visit_id DESC
        LIMIT 1
    """, (
        patient_id,
        today
    ))

    existing_visit = cursor.fetchone()

    if existing_visit:

        conn.close()

        return """
        <h1>今天已有預約</h1>

        <p>
            您今天已經有一筆進行中的預約。
        </p>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    # ==================================================
    # 情況一：患者已指定醫療院所
    # ==================================================

    if facility_id:

        # -------------------------
        # 確認醫療院所存在
        # -------------------------

        cursor.execute("""
            SELECT
                facility_id,
                name,
                facility_type,
                address,
                specialties,
                average_wait_minutes,
                daily_capacity
            FROM medical_facilities
            WHERE facility_id = %s
            LIMIT 1
        """, (
            facility_id,
        ))

        facility = cursor.fetchone()

        if not facility:

            conn.close()

            return """
            <h1>找不到醫療院所</h1>

            <p>
                您指定的醫療院所不存在。
            </p>

            <button onclick="location.href='/choose-facility'">
                返回
            </button>
            """

        (
            selected_facility_id,
            facility_name,
            facility_type,
            facility_address,
            specialties,
            average_wait,
            daily_capacity
        ) = facility

        # -------------------------
        # 計算今天已預約人數
        # -------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE facility_id = %s
            AND visit_date = %s
            AND status IN ('已預約', '已報到', '看診中')
        """, (
            selected_facility_id,
            today
        ))

        booked_count = cursor.fetchone()[0]

        available_slots = max(
            daily_capacity - booked_count,
            0
        )

        # -------------------------
        # 檢查名額
        # -------------------------

        if available_slots <= 0:

            conn.close()

            return """
            <h1>目前無法預約</h1>

            <p>
                很抱歉，這間院所今天的掛號名額已滿。
            </p>

            <button onclick="location.href='/choose-facility'">
                返回選擇醫療院所
            </button>
            """

        # -------------------------
        # 取得預約號碼
        # -------------------------

        cursor.execute("""
            SELECT COALESCE(
                MAX(appointment_number),
                0
            )
            FROM visits
            WHERE visit_date = %s
        """, (
            today,
        ))

        last_number = cursor.fetchone()[0]

        appointment_number = last_number + 1

        # -------------------------
        # 預約時間
        # -------------------------

        appointment_time = datetime.now(
            ZoneInfo("Asia/Taipei")
        ).strftime("%H:%M")

        # -------------------------
        # 建立預約
        # -------------------------

        cursor.execute("""
            INSERT INTO visits
            (
                patient_id,
                facility_id,
                visit_date,
                status,
                chief_complaint,
                appointment_number,
                appointment_time
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            RETURNING visit_id
        """, (
            patient_id,
            selected_facility_id,
            today,
            "已預約",
            chief_complaint,
            appointment_number,
            appointment_time
        ))

        visit_id = cursor.fetchone()[0]

        # -------------------------
        # 重新計算候診人數
        # -------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE facility_id = %s
            AND visit_date = %s
            AND status IN ('已預約', '已報到', '看診中')
        """, (
            selected_facility_id,
            today
        ))

        waiting_count = cursor.fetchone()[0]

        conn.commit()
        conn.close()

        # -------------------------
        # 預約成功
        # -------------------------

        return f"""
        <!DOCTYPE html>

        <html lang="zh-TW">

        <head>

            <meta charset="UTF-8">

            <meta
                name="viewport"
                content="width=device-width,
                         initial-scale=1.0"
            >

            <title>
                CareBridge - 預約成功
            </title>

        </head>

        <body>

            <h1>預約成功！</h1>

            <hr>

            <h2>您的預約</h2>

            <p>
                <strong>醫療院所：</strong>
                {facility_name}
            </p>

            <p>
                <strong>院所類型：</strong>
                {facility_type}
            </p>

            <p>
                <strong>地址：</strong>
                {facility_address}
            </p>

            <p>
                <strong>預約號碼：</strong>
                {appointment_number}
            </p>

            <p>
                <strong>預約時間：</strong>
                {appointment_time}
            </p>

            <p>
                <strong>本次症狀：</strong>
                {chief_complaint}
            </p>

            <hr>

            <p>
                <strong>目前預估等待：</strong>
                約 {average_wait} 分鐘
            </p>

            <p>
                <strong>目前候診人數：</strong>
                {waiting_count} 人
            </p>

            <hr>

            <button onclick="location.href='/patient-home'">
                回到患者首頁
            </button>

        </body>

        </html>
        """

    # ==================================================
    # 情況二：沒有指定醫療院所 → 系統推薦
    # ==================================================

    cursor.execute("""
        SELECT
            facility_id,
            name,
            facility_type,
            address,
            latitude,
            longitude,
            specialties,
            average_wait_minutes,
            daily_capacity
        FROM medical_facilities
    """)

    facilities = cursor.fetchall()

    if not facilities:

        conn.close()

        return """
        <h1>目前沒有可推薦的醫療院所</h1>

        <p>
            目前沒有可提供預約的醫療院所，
            請稍後再試。
        </p>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    # =========================
    # 建立推薦資料
    # =========================

    recommended_facilities = []

    for facility in facilities:

        (
            facility_id,
            name,
            facility_type,
            address,
            latitude,
            longitude,
            specialties,
            average_wait,
            daily_capacity
        ) = facility

        # -------------------------
        # 距離
        # -------------------------

        distance = calculate_distance(
            patient_latitude,
            patient_longitude,
            latitude,
            longitude
        )

        # -------------------------
        # 今天候診人數
        # -------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE facility_id = %s
            AND visit_date = %s
            AND status IN ('已預約', '已報到', '看診中')
        """, (
            facility_id,
            today
        ))

        waiting_count = cursor.fetchone()[0]

        # -------------------------
        # 剩餘名額
        # -------------------------

        available_slots = max(
            daily_capacity - waiting_count,
            0
        )

        # -------------------------
        # 推薦分數
        # -------------------------

        score = (
            distance * 0.3
            + average_wait * 0.5
            + waiting_count * 0.2
        )

        recommended_facilities.append({

            "facility": facility,

            "distance": distance,

            "waiting_count": waiting_count,

            "available_slots": available_slots,

            "score": score
        })

    # =========================
    # 排序
    # =========================

    recommended_facilities.sort(
        key=lambda x: x["score"]
    )

    # =========================
    # 建立推薦畫面
    # =========================

    facility_html = ""

    for index, item in enumerate(
        recommended_facilities,
        start=1
    ):

        facility = item["facility"]

        distance = item["distance"]

        waiting_count = item["waiting_count"]

        available_slots = item["available_slots"]

        (
            facility_id,
            name,
            facility_type,
            address,
            latitude,
            longitude,
            specialties,
            average_wait,
            daily_capacity
        ) = facility

        facility_html += f"""
        <div>

            <h2>
                第 {index} 推薦：{name}
            </h2>

            <p>
                <strong>院所類型：</strong>
                {facility_type}
            </p>

            <p>
                <strong>地址：</strong>
                {address}
            </p>

            <p>
                <strong>提供科別：</strong>
                {specialties}
            </p>

            <p>
                <strong>距離：</strong>
                約 {distance:.1f} 公里
            </p>

            <p>
                <strong>目前預估等待：</strong>
                約 {average_wait} 分鐘
            </p>

            <p>
                <strong>目前候診人數：</strong>
                {waiting_count} 人
            </p>

            <p>
                <strong>剩餘可掛號名額：</strong>
                {available_slots} 人
            </p>

            <form
                action="/select-facility"
                method="POST"
            >

                <input
                    type="hidden"
                    name="facility_id"
                    value="{facility_id}"
                >

                <input
                    type="hidden"
                    name="chief_complaint"
                    value="{chief_complaint}"
                >

                <button type="submit">
                    選擇這間院所
                </button>

            </form>

        </div>

        <hr>
        """

    conn.close()

    # =========================
    # 回傳推薦頁面
    # =========================

    return f"""
    <!DOCTYPE html>

    <html lang="zh-TW">

    <head>

        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width,
                     initial-scale=1.0"
        >

        <title>
            CareBridge - 醫療院所推薦
        </title>

    </head>

    <body>

        <h1>推薦醫療院所</h1>

        <p>
            系統會根據距離、
            預估等待時間及目前候診狀況
            進行推薦。
        </p>

        <hr>

        <h3>您的本次就醫原因</h3>

        <p>
            {chief_complaint}
        </p>

        <hr>

        {facility_html}

        <button
            onclick="location.href='/patient-home'"
        >
            回到患者首頁
        </button>

    </body>

    </html>
    """

@app.route("/select-facility", methods=["POST"])
def select_facility():

    if "patient_id" not in session:
        return redirect("/patient")

    patient_id = session["patient_id"]

    facility_id = request.form.get("facility_id")
    chief_complaint = request.form.get(
        "chief_complaint",
        ""
    ).strip()

    if not facility_id or not chief_complaint:
        return """
        <h1>資料不完整</h1>

        <p>
            無法建立預約，請重新輸入症狀。
        </p>

        <button onclick="location.href='/visit'">
            返回看診
        </button>
        """

    today = datetime.now(
        ZoneInfo("Asia/Taipei")
    ).strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # =========================
    # 確認醫療院所存在
    # =========================

    cursor.execute("""
        SELECT
            facility_id,
            name,
            facility_type,
            average_wait_minutes,
            daily_capacity
        FROM medical_facilities
        WHERE facility_id = %s
        LIMIT 1
    """, (facility_id,))

    facility = cursor.fetchone()

    if not facility:
        conn.close()

        return """
        <h1>找不到醫療院所</h1>

        <p>
            您選擇的醫療院所目前不存在，
            請重新選擇。
        </p>

        <button onclick="location.href='/visit'">
            返回醫療院所推薦
        </button>
        """

    (
        facility_id,
        facility_name,
        facility_type,
        average_wait,
        daily_capacity
    ) = facility

    cursor.execute("""
        SELECT COUNT(*)
        FROM visits
        WHERE facility_id = %s
        AND visit_date = %s
        AND status IN ('已預約', '已報到', '看診中')
    """, (
        facility_id,
        today
    ))

    booked_count = cursor.fetchone()[0]

    available_slots = max(
        daily_capacity - booked_count,
        0
    )

    # =========================
    # 檢查今天是否已有進行中的預約
    # =========================

    cursor.execute("""
        SELECT visit_id
        FROM visits
        WHERE patient_id = %s
        AND visit_date = %s
        AND status IN ('已預約', '已報到', '看診中')
        ORDER BY visit_id DESC
        LIMIT 1
    """, (
        patient_id,
        today
    ))

    existing_visit = cursor.fetchone()

    if existing_visit:
        conn.close()

        return """
        <h1>今天已有預約</h1>

        <p>
            您今天已經有一筆進行中的預約。
        </p>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    # =========================
    # 檢查是否還有掛號名額
    # =========================

    if available_slots <= 0:
        conn.close()

        return """
        <h1>目前無法預約</h1>

        <p>
            很抱歉，這間院所目前已沒有可用的掛號名額。
        </p>

        <button onclick="location.href='/visit'">
            返回重新選擇
        </button>
        """

    # =========================
    # 取得今天最後一個預約號碼
    # =========================

    cursor.execute("""
        SELECT COALESCE(MAX(appointment_number), 0)
        FROM visits
        WHERE facility_id = %s
        AND visit_date = %s
    """, (
        facility_id,
        today
    ))

    last_number = cursor.fetchone()[0]

    appointment_number = last_number + 1

    # =========================
    # 預約時間
    # =========================

    appointment_time = datetime.now(
        ZoneInfo("Asia/Taipei")
    ).strftime("%H:%M")

    # =========================
    # 建立預約
    # =========================

    cursor.execute("""
        INSERT INTO visits
        (
            patient_id,
            facility_id,
            visit_date,
            status,
            chief_complaint,
            appointment_number,
            appointment_time
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING visit_id
    """, (
        patient_id,
        facility_id,
        today,
        "已預約",
        chief_complaint,
        appointment_number,
        appointment_time
    ))

    visit_id = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM visits
        WHERE facility_id = %s
        AND visit_date = %s
        AND status IN ('已預約', '已報到')
    """, (
        facility_id,
        today
    ))

    waiting_count = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    return f"""
    <!DOCTYPE html>

    <html lang="zh-TW">

    <head>
        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width,
                     initial-scale=1.0"
        >

        <title>CareBridge - 預約成功</title>
    </head>

    <body>

        <h1>預約成功！</h1>

        <hr>

        <h2>您的預約</h2>

        <p>
            <strong>醫療院所：</strong>
            {facility_name}
        </p>

        <p>
            <strong>院所類型：</strong>
            {facility_type}
        </p>

        <p>
            <strong>預約號碼：</strong>
            {appointment_number}
        </p>

        <p>
            <strong>預約時間：</strong>
            {appointment_time}
        </p>

        <p>
            <strong>本次症狀：</strong>
            {chief_complaint}
        </p>

        <hr>

        <p>
            <strong>目前預估等待：</strong>
            約 {average_wait} 分鐘
        </p>

        <p>
            <strong>目前候診人數：</strong>
            {waiting_count} 人
        </p>

        <hr>

        <button
            onclick="location.href='/appointment-success/{appointment_number}'"
        >
            查看候診進度
        </button>

        <br><br>

        <button
            onclick="location.href='/patient-home'"
        >
            回到患者首頁
        </button>

    </body>

    </html>
    """

@app.route("/medical-recommendation")
def medical_recommendation():

    if "patient_id" not in session:
        return redirect("/patient")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 取得目前有資料的醫療院所
    cursor.execute("""
        SELECT
            facility_id,
            name,
            facility_type,
            address,
            specialties,
            average_wait_minutes,
            current_waiting_count,
            available_slots
        FROM medical_facilities
        ORDER BY average_wait_minutes ASC
    """)

    facilities = cursor.fetchall()

    conn.close()

    if not facilities:
        return """
        <h1>目前沒有可推薦的醫療院所</h1>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    result_html = """
    <h1>醫療院所推薦</h1>

    <p>
        以下依目前預估等待時間由短至長排列。
    </p>

    <hr>
    """

    for index, facility in enumerate(facilities, start=1):

        (
            facility_id,
            name,
            facility_type,
            address,
            latitude,
            longitude,
            specialties,
            average_wait,
            daily_capacity
        ) = facility

        # -------------------------
        # 計算目前候診人數
        # -------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE facility_id = %s
            AND visit_date = %s
            AND status IN ('已預約', '已報到')
        """, (
            facility_id,
            today
        ))

        waiting_count = cursor.fetchone()[0]

        # -------------------------
        # 計算今天已使用的掛號名額
        # -------------------------

        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE facility_id = %s
            AND visit_date = %s
            AND status IN ('已預約', '已報到', '看診中')
        """, (
            facility_id,
            today
        ))

        booked_count = cursor.fetchone()[0]

        # -------------------------
        # 計算剩餘名額
        # -------------------------

        available_slots = max(
            daily_capacity - booked_count,
            0
        )

        result_html += f"""
        <h2>第 {index} 推薦：{name}</h2>

        <p>
            <strong>院所類型：</strong>
            {facility_type}
        </p>

        <p>
            <strong>地址：</strong>
            {address}
        </p>

        <p>
            <strong>提供科別：</strong>
            {specialties}
        </p>

        <p>
            <strong>目前預估等待：</strong>
            約 {average_wait} 分鐘
        </p>

        <p>
            <strong>目前候診人數：</strong>
            {waiting_count} 人
        </p>

        <p>
            <strong>剩餘可掛號名額：</strong>
            {available_slots} 人
        </p>

        <hr>
        """

    result_html += """
    <button onclick="location.href='/patient-home'">
        回到患者首頁
    </button>
    """

    return result_html

@app.route("/health-info", methods=["GET", "POST"])
def health_info():

    if "patient_id" not in session:
        return redirect("/patient")

    patient_id = session["patient_id"]

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == "POST":

        disease = request.form.get(
            "disease", ""
        ).strip()

        allergy = request.form.get(
            "allergy", ""
        ).strip()

        medication = request.form.get(
            "medication", ""
        ).strip()

        family_history = request.form.get(
            "family_history", ""
        ).strip()

        cursor.execute("""
            UPDATE patients
            SET
                disease = %s,
                allergy = %s,
                medication = %s,
                family_history = %s
            WHERE patient_id = %s
        """, (
            disease,
            allergy,
            medication,
            family_history,
            patient_id
        ))

        conn.commit()
        conn.close()

        return redirect("/patient-home")

    cursor.execute("""
        SELECT
            disease,
            allergy,
            medication,
            family_history
        FROM patients
        WHERE patient_id = %s
    """, (patient_id,))

    health = cursor.fetchone()

    conn.close()

    if not health:
        return "找不到患者資料"

    return render_template(
        "health-info.html",
        disease=health[0] or "",
        allergy=health[1] or "",
        medication=health[2] or "",
        family_history=health[3] or ""
    )

@app.route("/create-visit", methods=["POST"])
def create_visit():

    if "patient_id" not in session:
        return redirect("/patient")

    patient_id = session["patient_id"]
    visit_date = datetime.now(
        ZoneInfo("Asia/Taipei")
    ).strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 避免同一天重複報到
    cursor.execute("""
        SELECT visit_id
        FROM visits
        WHERE patient_id = %s
        AND visit_date = %s
        AND status = '待看診'
    """, (
        patient_id,
        visit_date
    ))

    existing_visit = cursor.fetchone()

    if existing_visit:
        conn.close()

        return """
        <h1>您今天已經報到</h1>
        <p>請等待醫生處理您的就診。</p>

        <button onclick="location.href='/patient-home'">
            回到病患首頁
        </button>
        """

    cursor.execute("""
        INSERT INTO visits
        (patient_id, visit_date, status)
        VALUES (%s, %s, %s)
    """, (
        patient_id,
        visit_date,
        "已預約"
    ))

    conn.commit()
    conn.close()

    return """
    <h1>報到成功！</h1>
    <p>您已加入今日待看診名單。</p>

    <button onclick="location.href='/patient-home'">
        回到病患首頁
    </button>
    """

@app.route("/check-in", methods=["POST"])
def check_in():

    if "patient_id" not in session:
        return redirect("/patient")

    patient_id = session["patient_id"]
    visit_date = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT visit_id, status
        FROM visits
        WHERE patient_id = %s
        AND visit_date = %s
        AND status = '已預約'
        ORDER BY visit_id DESC
        LIMIT 1
    """, (patient_id, visit_date))

    visit = cursor.fetchone()

    if not visit:
        conn.close()

        return """
        <h1>目前沒有可報到的預約</h1>

        <button onclick="location.href='/patient-home'">
            回到病患首頁
        </button>
        """

    cursor.execute("""
        UPDATE visits
        SET status = '已報到'
        WHERE visit_id = %s
    """, (visit[0],))

    conn.commit()
    conn.close()

    return """
    <h1>報到成功！</h1>

    <p>您已完成報到，請等待醫生處理。</p>

    <button onclick="location.href='/patient-home'">
        回到病患首頁
    </button>
    """

@app.route("/appointment-success/<int:appointment_number>")
def appointment_success(appointment_number):

    if "patient_id" not in session:
        return redirect("/patient")

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 找到這位患者今天的預約
    cursor.execute("""
        SELECT
            visit_id,
            appointment_number,
            appointment_time,
            status,
            chief_complaint
        FROM visits
        WHERE patient_id = %s
        AND visit_date = %s
        AND appointment_number = %s
        LIMIT 1
    """, (
        session["patient_id"],
        today,
        appointment_number
    ))

    visit = cursor.fetchone()

    if not visit:
        conn.close()
        return "找不到預約資料"

    visit_id = visit[0]
    my_number = visit[1]
    appointment_time = visit[2]
    my_status = visit[3]
    chief_complaint = visit[4]

    # -------------------------
    # 預設值
    # -------------------------

    waiting_count = 0
    estimated_wait = 0
    current_number = "尚未叫號"
    estimated_time = "尚未估算"

    # -------------------------
    # 已預約
    # -------------------------

    if my_status == "已預約":

        # 已報到、看診中的人全部優先
        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE visit_date = %s
            AND status IN ('已報到', '看診中')
        """, (today,))

        checked_in_count = cursor.fetchone()[0]

        # 尚未報到但預約號碼比我小的人
        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE visit_date = %s
            AND status = '已預約'
            AND appointment_number < %s
        """, (today, my_number))

        earlier_reserved_count = cursor.fetchone()[0]

        waiting_count = (
            checked_in_count +
            earlier_reserved_count
        )

        # 每位患者暫定 10 分鐘
        estimated_wait = waiting_count * 10

        # 台灣時間
        taiwan_time = datetime.now(
            ZoneInfo("Asia/Taipei")
        )

        estimated_time = (
            taiwan_time +
            timedelta(minutes=estimated_wait)
        ).strftime("%H:%M")

    # -------------------------
    # 已報到
    # -------------------------

    elif my_status == "已報到":

        # 已報到且預約號碼比我小的人
        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE visit_date = %s
            AND status = '已報到'
            AND appointment_number < %s
        """, (today, my_number))

        earlier_checked_in = cursor.fetchone()[0]

        # 目前正在看診的人
        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE visit_date = %s
            AND status = '看診中'
        """, (today,))

        consulting_count = cursor.fetchone()[0]

        waiting_count = (
            earlier_checked_in +
            consulting_count
        )

        # 每位患者暫定 10 分鐘
        estimated_wait = waiting_count * 10

        # 台灣時間
        taiwan_time = datetime.now(
            ZoneInfo("Asia/Taipei")
        )

        estimated_time = (
            taiwan_time +
            timedelta(minutes=estimated_wait)
        ).strftime("%H:%M")

    # -------------------------
    # 看診中
    # -------------------------

    elif my_status == "看診中":

        waiting_count = 0
        estimated_wait = 0

        current_number = my_number

        estimated_time = "目前正在看診"

    # -------------------------
    # 已完成
    # -------------------------

    elif my_status == "已完成":

        waiting_count = 0
        estimated_wait = 0

        # 已完成就代表這個號碼已經看診完畢
        current_number = my_number

        estimated_time = "看診已完成"

    # -------------------------
    # 其他狀態
    # -------------------------

    else:

        waiting_count = 0
        estimated_wait = 0
        current_number = "尚未叫號"
        estimated_time = "尚未估算"

    conn.close()

    # -------------------------
    # 已完成
    # -------------------------

    if my_status == "已完成":

        return f"""
        <h1>看診已完成！</h1>

        <hr>

        <h2>我的預約</h2>

        <p>
            <strong>預約號碼：</strong>
            {my_number}
        </p>

        <p>
            <strong>預約時間：</strong>
            {appointment_time}
        </p>

        <p>
            <strong>目前狀態：</strong>
            已完成
        </p>

        <hr>

        <h2>本次看診</h2>

        <p>
            <strong>看診狀態：</strong>
            本次看診已完成
        </p>

        <p>
            <strong>本次症狀：</strong>
            {chief_complaint}
        </p>

        <hr>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    # -------------------------
    # 一般候診狀態
    # -------------------------

    return f"""
    <h1>預約成功！</h1>

    <hr>

    <h2>我的預約</h2>

    <p>
        <strong>預約號碼：</strong>
        {my_number}
    </p>

    <p>
        <strong>預約時間：</strong>
        {appointment_time}
    </p>

    <p>
        <strong>目前狀態：</strong>
        {my_status}
    </p>

    <p>
        <strong>本次症狀：</strong>
        {chief_complaint}
    </p>

    <hr>

    <h2>目前候診資訊</h2>

    <p>
        <strong>目前叫號：</strong>
        {current_number}
    </p>

    <p>
        <strong>前方等待人數：</strong>
        {waiting_count} 人
    </p>

    <p>
        <strong>預估等待時間：</strong>
        約 {estimated_wait} 分鐘
    </p>

    <p>
        <strong>預計看診時間：</strong>
        約 {estimated_time}
    </p>

    <hr>

    <p>
        預約完成後，請於看診前至醫院報到櫃台完成報到。
    </p>

    <button onclick="location.href='/patient-home'">
        回到患者首頁
    </button>
    """

@app.route("/patient-fhir")
def patient_fhir():

    if "patient_id" not in session:
        return redirect("/patient")

    # =========================
    # 連接 PostgreSQL
    # =========================

    conn = get_db()
    cursor = conn.cursor()

    patient_id = session["patient_id"]

    # =========================
    # 取得患者基本資料
    # =========================

    cursor.execute("""
        SELECT 
            patient_id,
            name,
            birth_date,
            gender,
            phone,
            disease,
            allergy,
            medication,
            family_history
        FROM patients
        WHERE patient_id = %s
    """, (patient_id,))

    patient = cursor.fetchone()

    # =========================
    # 取得歷史看診
    # =========================

    cursor.execute("""
        SELECT
            visit_date,
            diagnosis,
            prescription,
            chief_complaint
        FROM visits
        WHERE patient_id = %s
        AND status = '已完成'
        ORDER BY visit_date DESC
    """, (patient_id,))

    visits = cursor.fetchall()

    conn.close()

    # =========================
    # 找不到患者
    # =========================

    if not patient:
        return "找不到病患資料"

    # =========================
    # Patient
    # =========================

    fhir_patient = {

        "resourceType": "Patient",

        "id": patient[0],

        "name": [
            {
                "text": patient[1]
            }
        ],

        "gender": patient[3],

        "birthDate": patient[2],

        "telecom": [
            {
                "system": "phone",
                "value": patient[4]
            }
        ]

    }

    # =========================
    # 慢性病
    # =========================

    chronic_condition = None

    if patient[5]:

        chronic_condition = build_chronic_condition_fhir(
            patient[0],
            patient[0],
            patient[5]
        )

    # =========================
    # 過敏
    # =========================

    allergy = None

    if patient[6]:

        allergy = build_allergy_fhir(
            patient[0],
            patient[0],
            patient[6]
        )

    # =========================
    # 長期用藥
    # =========================

    medication = None

    if patient[7]:

        medication = build_medication_fhir(
            patient[0],
            patient[0],
            patient[7]
        )

    # =========================
    # 家族史
    # =========================

    family_history = None

    if patient[8]:

        family_history = build_family_history_fhir(
            patient[0],
            patient[0],
            patient[8]
        )

    # =========================
    # 歷史診斷與處方
    # =========================

    diagnosis_conditions = []

    prescription_requests = []

    for visit in visits:

        visit_date = visit[0]
        diagnosis = visit[1]
        prescription = visit[2]
        complaint = visit[3]

        # -------------------------
        # 診斷結果
        # -------------------------

        if diagnosis:

            diagnosis_conditions.append(
                build_condition_fhir(
                    patient[0],
                    patient[0],
                    visit_date,
                    diagnosis
                )
            )

        # -------------------------
        # 處方
        # -------------------------

        if prescription:

            prescription_requests.append(
                build_medication_request_fhir(
                    patient[0],
                    patient[0],
                    visit_date,
                    prescription
                )
            )

    # =========================
    # 顯示 FHIR
    # =========================

    return f"""

    <h1>FHIR Patient 資料</h1>

    <h2>Patient</h2>

    <pre>{json.dumps(
        fhir_patient,
        ensure_ascii=False,
        indent=2
    )}</pre>

    <h2>Condition（慢性病）</h2>

    <pre>{json.dumps(
        chronic_condition,
        ensure_ascii=False,
        indent=2
    )}</pre>

    <h2>Condition（診斷結果）</h2>

    <pre>{json.dumps(
        diagnosis_conditions,
        ensure_ascii=False,
        indent=2
    )}</pre>

    <h2>MedicationRequest（醫師處方）</h2>

    <pre>{json.dumps(
        prescription_requests,
        ensure_ascii=False,
        indent=2
    )}</pre>

    <h2>AllergyIntolerance（過敏史）</h2>

    <pre>{json.dumps(
        allergy,
        ensure_ascii=False,
        indent=2
    )}</pre>

    <h2>MedicationStatement（長期用藥）</h2>

    <pre>{json.dumps(
        medication,
        ensure_ascii=False,
        indent=2
    )}</pre>

    <h2>FamilyMemberHistory（家族疾病史）</h2>

    <pre>{json.dumps(
        family_history,
        ensure_ascii=False,
        indent=2
    )}</pre>

    <br>

    <button onclick="location.href='/patient-home'">
        回到患者首頁
    </button>

    """

@app.route("/send-fhir", methods=["POST"])
def send_fhir():

    if "patient_id" not in session:
        return redirect("/patient")

    # =========================
    # 從 PostgreSQL 取得患者資料
    # =========================

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            patient_id,
            name,
            birth_date,
            gender,
            phone,
            disease,
            allergy,
            medication,
            family_history
        FROM patients
        WHERE patient_id = %s
    """, (session["patient_id"],))

    patient = cursor.fetchone()

    cursor.close()
    conn.close()

    if not patient:
        return "找不到病患資料"

    # =========================
    # 建立 FHIR Patient
    # =========================

    fhir_patient = build_patient_fhir(patient)

    fhir_server_url = (
        "https://hapi.fhir.org/baseR4/Patient"
    )

    # =========================
    # 搜尋 Patient 是否已存在
    # =========================

    search_url = (
        "https://hapi.fhir.org/baseR4/Patient"
    )

    search_response = requests.get(
        search_url,
        params={
            "identifier":
                "https://carebridge.example/patient-id|"
                + patient[0]
        },
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60
    )

    if search_response.status_code != 200:

        return f"""
        <h1>FHIR Server 查詢失敗</h1>

        <p>
            HTTP Status Code：
            {search_response.status_code}
        </p>

        <pre>{search_response.text}</pre>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    search_result = search_response.json()

    print(
        json.dumps(
            search_result,
            indent=2,
            ensure_ascii=False
        )
    )

    # =========================
    # 建立 / 更新 Patient
    # =========================

    if search_result.get("total", 0) > 0:

        existing_patient = (
            search_result["entry"][0]["resource"]
        )

        fhir_patient_id = existing_patient["id"]

        fhir_patient["id"] = fhir_patient_id

        update_url = (
            f"https://hapi.fhir.org/baseR4/"
            f"Patient/{fhir_patient_id}"
        )

        response = requests.put(
            update_url,
            json=fhir_patient,
            headers={
                "Content-Type":
                    "application/fhir+json"
            },
            timeout=60
        )

    else:

        response = requests.post(
            fhir_server_url,
            json=fhir_patient,
            headers={
                "Content-Type":
                    "application/fhir+json"
            },
            timeout=60
        )

    # =========================
    # Patient 建立 / 更新失敗
    # =========================

    if response.status_code not in [200, 201]:

        return f"""
        <h1>FHIR Patient 建立/更新失敗</h1>

        <p>
            HTTP Status Code：
            {response.status_code}
        </p>

        <pre>{response.text}</pre>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    # =========================
    # 新建立的 Patient 取得 FHIR ID
    # =========================

    if search_result.get("total", 0) == 0:

        created_patient = response.json()

        fhir_patient_id = created_patient["id"]

    # ==================================================
    # 預設顯示文字
    # ==================================================

    condition_text = "沒有慢性病資料"
    condition_response_text = ""

    allergy_text = "沒有過敏史資料"
    allergy_response_text = ""

    medication_text = "沒有長期用藥資料"
    medication_response_text = ""

    family_text = "沒有家族疾病史資料"
    family_response_text = ""

    # ==================================================
    # 1. 慢性病 Condition
    # ==================================================

    if patient[5]:

        condition = build_chronic_condition_fhir(
            fhir_patient_id,
            patient[0],
            patient[5]
        )

        condition_id, condition_response = (
            upload_or_update_resource(
                "Condition",
                condition,
                "https://carebridge.example/patient-id",
                patient[0] + "-chronic-condition"
            )
        )

        condition_text = (
            f"慢性病：{patient[5]}"
        )

        condition_response_text = f"""
        <p>
            Condition HTTP Status Code：
            {condition_response.status_code}
        </p>

        <pre>{condition_response.text}</pre>
        """

    # ==================================================
    # 2. 過敏史 AllergyIntolerance
    # ==================================================

    if patient[6]:

        allergy = build_allergy_fhir(
            fhir_patient_id,
            patient[0],
            patient[6]
        )

        allergy_id, allergy_response = (
            upload_or_update_resource(
                "AllergyIntolerance",
                allergy,
                "https://carebridge.example/patient-id",
                patient[0] + "-allergy"
            )
        )

        allergy_text = (
            f"過敏史：{patient[6]}"
        )

        allergy_response_text = f"""
        <p>
            AllergyIntolerance HTTP Status Code：
            {allergy_response.status_code}
        </p>

        <pre>{allergy_response.text}</pre>
        """

    # ==================================================
    # 3. 長期用藥 MedicationStatement
    # ==================================================

    if patient[7]:

        medication = build_medication_fhir(
            fhir_patient_id,
            patient[0],
            patient[7]
        )

        medication_id, medication_response = (
            upload_or_update_resource(
                "MedicationStatement",
                medication,
                "https://carebridge.example/patient-id",
                patient[0] + "-medication"
            )
        )

        medication_text = (
            f"長期用藥：{patient[7]}"
        )

        medication_response_text = f"""
        <p>
            MedicationStatement HTTP Status Code：
            {medication_response.status_code}
        </p>

        <pre>{medication_response.text}</pre>
        """

    # ==================================================
    # 4. 家族疾病史 FamilyMemberHistory
    # ==================================================

    if patient[8]:

        family = build_family_history_fhir(
            fhir_patient_id,
            patient[0],
            patient[8]
        )

        family_id, family_response = (
            upload_or_update_resource(
                "FamilyMemberHistory",
                family,
                "https://carebridge.example/patient-id",
                patient[0] + "-family-history"
            )
        )

        family_text = (
            f"家族疾病史：{patient[8]}"
        )

        family_response_text = f"""
        <p>
            FamilyMemberHistory HTTP Status Code：
            {family_response.status_code}
        </p>

        <pre>{family_response.text}</pre>
        """

    # ==================================================
    # 5. 歷史看診資料
    # ==================================================

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            visit_date,
            diagnosis,
            prescription
        FROM visits
        WHERE patient_id = %s
        AND status = '已完成'
        ORDER BY visit_date DESC
    """, (patient[0],))

    visits = cursor.fetchall()

    cursor.close()
    conn.close()

    # ==================================================
    # 上傳歷史診斷與處方
    # ==================================================

    visit_response_text = ""

    for visit in visits:

        visit_date = visit[0]
        diagnosis = visit[1]
        prescription = visit[2]

        # -------------------------
        # 診斷
        # -------------------------

        if diagnosis:

            diagnosis_condition = (
                build_condition_fhir(
                    fhir_patient_id,
                    patient[0],
                    visit_date,
                    diagnosis
                )
            )

            diagnosis_id, diagnosis_response = (
                upload_or_update_resource(
                    "Condition",
                    diagnosis_condition,
                    "https://carebridge.example/visit-diagnosis",
                    patient[0] + "-" + str(visit_date)
                )
            )

            visit_response_text += f"""
            <h3>診斷：{diagnosis}</h3>

            <p>
                Condition HTTP Status Code：
                {diagnosis_response.status_code}
            </p>

            <pre>{diagnosis_response.text}</pre>
            """

        # -------------------------
        # 處方
        # -------------------------

        if prescription:

            medication_request = (
                build_medication_request_fhir(
                    fhir_patient_id,
                    patient[0],
                    visit_date,
                    prescription
                )
            )

            medication_request_id, medication_request_response = (
                upload_or_update_resource(
                    "MedicationRequest",
                    medication_request,
                    "https://carebridge.example/visit-prescription",
                    patient[0] + "-" + str(visit_date)
                )
            )

            visit_response_text += f"""
            <h3>處方：{prescription}</h3>

            <p>
                MedicationRequest HTTP Status Code：
                {medication_request_response.status_code}
            </p>

            <pre>{medication_request_response.text}</pre>
            """

    # ==================================================
    # 顯示結果
    # ==================================================

    return f"""
    <h1>FHIR Server 傳送結果</h1>

    <p>
        <strong>FHIR Patient ID：</strong>
        {fhir_patient_id}
    </p>

    <p>
        Patient 已成功處理。
    </p>

    <hr>

    <h2>慢性病 Condition</h2>

    <p>{condition_text}</p>

    {condition_response_text}

    <hr>

    <h2>過敏史（FHIR AllergyIntolerance）</h2>

    <p>{allergy_text}</p>

    {allergy_response_text}

    <hr>

    <h2>長期用藥（FHIR MedicationStatement）</h2>

    <p>{medication_text}</p>

    {medication_response_text}

    <hr>

    <h2>家族疾病史（FHIR FamilyMemberHistory）</h2>

    <p>{family_text}</p>

    {family_response_text}

    <hr>

    <h2>歷史看診資料</h2>

    {visit_response_text}

    <br>

    <button onclick="location.href='/patient-home'">
        回到患者首頁
    </button>
    """

@app.route("/get-fhir")
def get_fhir():
    if "patient_id" not in session:
        return redirect("/patient")

    patient_id = session["patient_id"]

    search_url = (
        "https://hapi.fhir.org/baseR4/Patient"
        "?identifier=https://carebridge.example/patient-id|"
        + patient_id
    )

    response = requests.get(
        search_url,
        headers={
            "Accept": "application/fhir+json"
        },
        timeout=60
    )

    if response.status_code != 200:
        return f"""
        <h1>FHIR Server 查詢失敗</h1>
        <p>HTTP Status Code：{response.status_code}</p>
        <pre>{response.text}</pre>

        <br>

        <button onclick="location.href='/patient-home'">
            回到病患首頁
        </button>
        """

    result = response.json()

    if result.get("total", 0) == 0:
        return """
        <h1>找不到患者資料</h1>
        <p>FHIR Server 中沒有找到這位患者。</p>

        <br>

        <button onclick="location.href='/patient-home'">
            回到病患首頁
        </button>
        """

    fhir_patient = result["entry"][0]["resource"]
    fhir_patient_id = fhir_patient["id"]

    condition_response = requests.get(
        f"https://hapi.fhir.org/baseR4/Condition?subject=Patient/{fhir_patient_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60
    )

    condition_result = condition_response.json()

    if condition_result.get("total", 0) > 0:
        condition = condition_result["entry"][0]["resource"]
    else:
        condition = None

    allergy_response = requests.get(
        f"https://hapi.fhir.org/baseR4/AllergyIntolerance?patient=Patient/{fhir_patient_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60
    )

    allergy_result = allergy_response.json()

    if allergy_result.get("total", 0) > 0:
        allergy = allergy_result["entry"][0]["resource"]
    else:
        allergy = None

    medication_response = requests.get(
        f"https://hapi.fhir.org/baseR4/MedicationStatement?patient=Patient/{fhir_patient_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60
    )

    medication_result = medication_response.json()

    if medication_result.get("total", 0) > 0:
        medication = medication_result["entry"][0]["resource"]
    else:
        medication = None

    family_response = requests.get(
        f"https://hapi.fhir.org/baseR4/FamilyMemberHistory?patient=Patient/{fhir_patient_id}",
        headers={"Accept": "application/fhir+json"},
        timeout=60
    )

    family_result = family_response.json()

    if family_result.get("total", 0) > 0:
        family_history = family_result["entry"][0]["resource"]
    else:
        family_history = None

    return f"""
    <h1>從 FHIR Server 查詢到的患者資料</h1>

    <h2>Patient</h2>
    <pre>{json.dumps(fhir_patient, ensure_ascii=False, indent=2)}</pre>

    <h2>Condition（慢性病）</h2>
    <pre>{json.dumps(condition, ensure_ascii=False, indent=2)}</pre>

    <h2>AllergyIntolerance（過敏史）</h2>
    <pre>{json.dumps(allergy, ensure_ascii=False, indent=2)}</pre>

    <h2>MedicationStatement（長期用藥）</h2>
    <pre>{json.dumps(medication, ensure_ascii=False, indent=2)}</pre>

    <h2>FamilyMemberHistory（家族疾病史）</h2>
    <pre>{json.dumps(family_history, ensure_ascii=False, indent=2)}</pre>

    <br>

    <button onclick="location.href='/patient-home'">
        回到病患首頁
    </button>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# 病患註冊
@app.route("/register", methods=["GET", "POST"])
def register():

    # GET：顯示註冊頁面
    if request.method == "GET":
        return render_template("patient-register.html")

    # POST：接收註冊資料
    name = request.form.get("name")
    id_number = request.form.get(
        "id_number",
        ""
    ).strip().upper()

    birth_date = request.form.get("birthDate")
    gender = request.form.get("gender")
    phone = request.form.get("phone")

    disease = request.form.get("disease")
    allergy = request.form.get("allergy")
    medication = request.form.get("medication")

    # 檢查身分證字號是否已註冊
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT patient_id
        FROM patients
        WHERE id_number = %s
        LIMIT 1
    """, (id_number,))

    existing_patient = cursor.fetchone()

    if existing_patient:
        conn.close()

        return """
        <h1>註冊失敗</h1>

        <p>此身分證字號已經註冊過。</p>

        <button onclick="location.href='/patient'">
            回到患者登入
        </button>
        """

    # 產生 CareBridge Patient ID
    patient_id = "CB-" + str(uuid.uuid4())[:8].upper()

    # 將資料存進 SQLite
    cursor.execute("""
        INSERT INTO patients
        (
            patient_id,
            id_number,
            name,
            birth_date,
            gender,
            phone,
            disease,
            allergy,
            medication
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        patient_id,
        id_number,
        name,
        birth_date,
        gender,
        phone,
        disease,
        allergy,
        medication
    ))

    conn.commit()
    conn.close()

    # 記住登入狀態
    session["patient_name"] = name
    session["patient_id"] = patient_id

    # 前往患者首頁
    return redirect("/patient-home")

@app.route("/current-call")
def current_call():

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT appointment_number
        FROM visits
        WHERE visit_date = %s
        AND status = '看診中'
        ORDER BY started_at DESC
        LIMIT 1
    """, (today,))

    current = cursor.fetchone()

    conn.close()

    if current:
        return {
            "current_number": current[0]
        }

    return {
        "current_number": None
    }

@app.route("/my-queue")
def my_queue():

    if "patient_id" not in session:
        return redirect("/patient")

    patient_id = session["patient_id"]
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    # 找到患者今天最新的一筆預約
    cursor.execute("""
        SELECT
            visit_id,
            appointment_number,
            appointment_time,
            status
        FROM visits
        WHERE patient_id = %s
        AND visit_date = %s
        ORDER BY visit_id DESC
        LIMIT 1
    """, (patient_id, today))

    visit = cursor.fetchone()

    if not visit:
        conn.close()

        return """
        <h1>目前沒有今日預約</h1>

        <button onclick="location.href='/patient-home'">
            回到患者首頁
        </button>
        """

    appointment_number = visit[1]
    status = visit[3]

    # -------------------------
    # 計算前方等待人數
    # -------------------------

    waiting_ahead = 0

    if status == "已預約":

        # 已報到或看診中的人優先
        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE visit_date = %s
            AND status IN ('已報到', '看診中')
        """, (today,))

        priority_count = cursor.fetchone()[0]

        # 比自己更早的未報到預約
        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE visit_date = %s
            AND status = '已預約'
            AND appointment_number < %s
        """, (today, appointment_number))

        earlier_reserved = cursor.fetchone()[0]

        waiting_ahead = (
            priority_count +
            earlier_reserved
        )

    elif status == "已報到":

        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE visit_date = %s
            AND status = '已報到'
            AND appointment_number < %s
        """, (today, appointment_number))

        earlier_checked_in = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM visits
            WHERE visit_date = %s
            AND status = '看診中'
        """, (today,))

        consulting_count = cursor.fetchone()[0]

        waiting_ahead = (
            earlier_checked_in +
            consulting_count
        )

    elif status == "看診中":
        waiting_ahead = 0

    elif status == "已完成":
        waiting_ahead = 0

    # -------------------------
    # 目前叫號
    # -------------------------

    cursor.execute("""
        SELECT appointment_number
        FROM visits
        WHERE visit_date = %s
        AND status = '看診中'
        ORDER BY started_at DESC
        LIMIT 1
    """, (today,))

    current_call = cursor.fetchone()

    if current_call:
        current_number = current_call[0]
    else:
        current_number = "尚未叫號"

    # -------------------------
    # 預估等待時間
    # -------------------------

    cursor.execute("""
        SELECT started_at, completed_at
        FROM visits
        WHERE visit_date = %s
        AND status = '已完成'
        AND started_at IS NOT NULL
        AND completed_at IS NOT NULL
    """, (today,))

    completed_visits = cursor.fetchall()

    if completed_visits:

        durations = []

        for started_at, completed_at in completed_visits:

            start_time = datetime.strptime(
                started_at,
                "%Y-%m-%d %H:%M:%S"
            )

            end_time = datetime.strptime(
                completed_at,
                "%Y-%m-%d %H:%M:%S"
            )

            duration = (
                end_time - start_time
            ).total_seconds() / 60

            durations.append(duration)

        average_duration = sum(durations) / len(durations)

    else:
        average_duration = 10

    estimated_wait = round(
        waiting_ahead * average_duration
    )


    taiwan_time = datetime.now(ZoneInfo("Asia/Taipei"))

    estimated_time = (
        taiwan_time +
        timedelta(minutes=estimated_wait)
    ).strftime("%H:%M")

    print("DEBUG Taiwan time:", taiwan_time)
    print("DEBUG estimated time:", estimated_time)

    conn.close()

    return render_template(
        "my-queue.html",
        appointment_number=appointment_number,
        appointment_time=visit[2],
        status=status,
        current_number=current_number,
        waiting_ahead=waiting_ahead,
        estimated_wait=estimated_wait,
        estimated_time=estimated_time
    )

@app.route("/hospital-login", methods=["GET", "POST"])
def hospital_login():

    if request.method == "GET":
        return render_template("hospital-login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    # 先用測試帳號
    if username == "hospital" and password == "5678":

        session["hospital_user"] = username

        return redirect("/hospital")

    return """
    <h1>登入失敗</h1>

    <p>帳號或密碼錯誤。</p>

    <button onclick="location.href='/hospital-login'">
        返回登入
    </button>
    """
   
@app.route("/hospital-prescription", methods=["GET", "POST"])
def hospital_prescription():

    if "hospital_user" not in session:
        return redirect("/hospital-login")

    # GET：顯示查詢頁
    if request.method == "GET":
        return render_template("hospital-prescription.html")

    id_number = request.form.get(
        "id_number",
        ""
    ).strip().upper()

    if not id_number:
        return """
        <h1>請輸入身分證字號</h1>

        <button onclick="location.href='/hospital-prescription'">
            返回
        </button>
        """

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            visits.visit_id,
            patients.name,
            patients.id_number,
            patients.patient_id,
            visits.visit_date,
            visits.appointment_number,
            visits.appointment_time,
            visits.chief_complaint,
            visits.diagnosis,
            visits.prescription,
            visits.completed_at,
            visits.status
        FROM visits
        JOIN patients
            ON visits.patient_id = patients.patient_id
        WHERE patients.id_number = %s
        AND visits.status = '已完成'
        ORDER BY visits.visit_date DESC,
                visits.visit_id DESC
    """, (id_number,))

    visits = cursor.fetchall()

    print(visits)

    conn.close()

    if not visits:
        return """
        <h1>找不到今日已完成的看診</h1>

        <p>
            請確認身分證字號，或確認患者今天是否已完成看診。
        </p>

        <button onclick="location.href='/hospital-prescription'">
            返回
        </button>
        """

    return render_template(
        "hospital-prescription-result.html",
        visits=visits
    )

@app.route("/hospital-prescription-detail/<int:visit_id>")
def hospital_prescription_detail(visit_id):

    print("visit_id =", visit_id)

    if "hospital_user" not in session:
        return redirect("/hospital-login")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        visits.visit_id,
        patients.name,
        patients.id_number,
        patients.patient_id,
        visits.visit_date,
        visits.appointment_number,
        visits.appointment_time,
        visits.chief_complaint,
        visits.diagnosis,
        visits.prescription,
        visits.completed_at,
        visits.status
    FROM visits
    JOIN patients
        ON visits.patient_id = patients.patient_id
    WHERE visits.visit_id = %s
""", (visit_id,))

    visit = cursor.fetchone()

    print("visit =", visit)

    conn.close()

    if not visit:
        return """
        <h1>找不到這筆看診資料</h1>

        <button onclick="location.href='/hospital-prescription'">
            回到歷史處方
        </button>
        """

    return render_template(
        "hospital-prescription-detail.html",
        visit=visit
    )

@app.route("/hospital-logout")
def hospital_logout():

    session.pop("hospital_user", None)

    return redirect("/hospital-login")

@app.route("/hospital")
def hospital():

    if "hospital_user" not in session:
        return redirect("/hospital-login")

    return render_template(
        "hospital.html",
        hospital_user=session["hospital_user"]
    )

@app.route("/check-db")
def check_db():

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            column_name,
            is_identity,
            column_default
        FROM information_schema.columns
        WHERE table_name = 'visits'
        AND column_name = 'visit_id'
    """)

    result = cursor.fetchone()

    conn.close()

    return f"""
    <h1>Database Check</h1>
    <pre>{result}</pre>
    """

@app.route("/fix-db")
def fix_db():

    conn = get_db_connection()
    cursor = conn.cursor()

    # 確認目前最大的 visit_id
    cursor.execute("""
        SELECT COALESCE(MAX(visit_id), 0)
        FROM visits
    """)

    max_visit_id = cursor.fetchone()[0]

    # 取得目前 visit_id 的 identity sequence
    cursor.execute("""
        SELECT pg_get_serial_sequence('visits', 'visit_id')
    """)

    sequence_name = cursor.fetchone()[0]

    if sequence_name:

        cursor.execute(
            "SELECT setval(%s, %s, true)",
            (
                sequence_name,
                max_visit_id
            )
        )

    conn.commit()

    # 再確認
    cursor.execute("""
        SELECT
            column_name,
            is_identity,
            column_default
        FROM information_schema.columns
        WHERE table_name = 'visits'
        AND column_name = 'visit_id'
    """)

    result = cursor.fetchone()

    conn.close()

    return f"""
    <h1>Database Fixed</h1>

    <p>目前最大的 visit_id：{max_visit_id}</p>

    <p>Identity 狀態：</p>

    <pre>{result}</pre>

    <p>Sequence：</p>

    <pre>{sequence_name}</pre>
    """

init_db()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )


