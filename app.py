from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

# กำหนด Path ไฟล์ฐานข้อมูลให้คงที่ในโฟลเดอร์โปรเจกต์ เพื่อเก็บข้อมูลถาวรทุกครั้งที่เปิดใหม่
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "reaction_game.db")

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # 1. ตารางข้อมูลนักกีฬา (Athletes)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS athletes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                sport_type TEXT DEFAULT 'ทั่วไป',
                created_at TEXT
            )
        ''')
        # 2. ตารางรอบการฝึกซ้อม (Sessions)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                athlete_id INTEGER,
                mode TEXT NOT NULL,
                total_lights INTEGER DEFAULT 5,
                total_hits INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                avg_time_ms REAL,
                best_time_ms REAL,
                created_at TEXT,
                FOREIGN KEY (athlete_id) REFERENCES athletes (id)
            )
        ''')
        # 3. ตารางบันทึกสถิติเชิงลึก (Logs)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                round_no INTEGER,
                light_number INTEGER,
                response_time_ms REAL,
                status TEXT DEFAULT 'valid',
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        ''')

        # อัปเกรดคอลัมน์อัตโนมัติ (กรณีมีไฟล์ .db เก่าอยู่แล้ว จะไม่ลบข้อมูลเดิม)
        existing_session_cols = [col[1] for col in cursor.execute("PRAGMA table_info(sessions)")]
        if "total_hits" not in existing_session_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN total_hits INTEGER DEFAULT 0")
        if "errors" not in existing_session_cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN errors INTEGER DEFAULT 0")

        existing_log_cols = [col[1] for col in cursor.execute("PRAGMA table_info(logs)")]
        if "status" not in existing_log_cols:
            cursor.execute("ALTER TABLE logs ADD COLUMN status TEXT DEFAULT 'valid'")

        conn.commit()

@app.route('/')
def index():
    return render_template('index.html')

# API: ดึงรายชื่อผู้เล่นทั้งหมดที่เคยบันทึกไว้ (ใช้ทำ Autocomplete ก่อนเริ่มเกม)
@app.route('/api/athletes', methods=['GET'])
def get_athletes():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, sport_type FROM athletes ORDER BY name ASC")
        return jsonify([dict(row) for row in cursor.fetchall()])

# API: ดึงข้อมูลแดชบอร์ดและประวัติทั้งหมดจากฐานข้อมูลถาวร
@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT s.id, a.name as athlete_name, a.sport_type, s.mode,
                   s.total_hits, s.errors, s.avg_time_ms, s.best_time_ms, s.created_at
            FROM sessions s
            LEFT JOIN athletes a ON s.athlete_id = a.id
            ORDER BY s.id DESC
        ''')
        sessions = [dict(row) for row in cursor.fetchall()]

        cursor.execute('''
            SELECT COUNT(*) as total,
                   AVG(avg_time_ms) as overall_avg,
                   MIN(best_time_ms) as overall_best
            FROM sessions
            WHERE avg_time_ms > 0
        ''')
        summary = dict(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) as total_players FROM athletes")
        summary["total_players"] = cursor.fetchone()["total_players"]

        return jsonify({"summary": summary, "sessions": sessions})

# API: ดึงรายละเอียดการกด (Logs) ของแต่ละรอบ
@app.route('/api/sessions/<int:session_id>/logs', methods=['GET'])
def get_session_logs(session_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM logs WHERE session_id = ? ORDER BY round_no ASC", (session_id,))
        return jsonify([dict(row) for row in cursor.fetchall()])

# API: บันทึกผลการเล่น (สร้างชื่อผู้เล่นใหม่อัตโนมัติหากยังไม่มี หรือใช้ ID เดิมหากเคยเล่นแล้ว)
@app.route('/api/save_game', methods=['POST'])
def save_game():
    data = request.json
    player_name = (data.get('player_name') or '').strip()
    sport_type = (data.get('sport_type') or 'ทั่วไป').strip()
    mode = data.get('mode', 'Choice Reaction')
    total_lights = data.get('total_lights', 5)
    errors = data.get('errors', 0)
    logs = data.get('logs', [])

    if not player_name:
        return jsonify({"status": "error", "message": "กรุณาระบุชื่อผู้เล่น"}), 400

    valid_times = [item['response_time_ms'] for item in logs if item.get('status') == 'valid']
    avg_time = round(sum(valid_times) / len(valid_times), 2) if valid_times else 0
    best_time = round(min(valid_times), 2) if valid_times else 0
    total_hits = len(valid_times)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # ค้นหาชื่อผู้เล่นเดิม (ไม่สนตัวพิมพ์เล็ก-ใหญ่)
        cursor.execute("SELECT id FROM athletes WHERE LOWER(name) = LOWER(?)", (player_name,))
        row = cursor.fetchone()
        if row:
            athlete_id = row[0]
            if sport_type and sport_type != 'ทั่วไป':
                cursor.execute("UPDATE athletes SET sport_type = ? WHERE id = ?", (sport_type, athlete_id))
        else:
            cursor.execute(
                "INSERT INTO athletes (name, sport_type, created_at) VALUES (?, ?, ?)",
                (player_name, sport_type, now_str)
            )
            athlete_id = cursor.lastrowid

        cursor.execute('''
            INSERT INTO sessions (athlete_id, mode, total_lights, total_hits, errors, avg_time_ms, best_time_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (athlete_id, mode, total_lights, total_hits, errors, avg_time, best_time, now_str))
        session_id = cursor.lastrowid

        for item in logs:
            cursor.execute('''
                INSERT INTO logs (session_id, round_no, light_number, response_time_ms, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, item['round_no'], item['light_number'], item['response_time_ms'], item.get('status', 'valid')))
        conn.commit()

    return jsonify({
        "status": "success",
        "session_id": session_id,
        "avg_time_ms": avg_time,
        "best_time_ms": best_time
    })
init_db()
if __name__ == '__main__':
    print(f"Database connected at: {DB_NAME}")
    app.run(debug=True, host='0.0.0.0', port=5000)