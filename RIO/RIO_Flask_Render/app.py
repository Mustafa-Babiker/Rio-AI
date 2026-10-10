import os
import sqlite3
import secrets
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, session
from google import genai

# ============================================================
# RIO CONFIGURATION
# Paste your NEW keys between the quotes below.
# Do not use a Gemini API key that has already been exposed.
# ============================================================
SECRET_KEY = "e3982c9f526afb7c2e0ec3a91ccccd791a458bfb6e8c0fd5c245eb082069c50c"
GEMINI_API_KEY = "AQ.Ab8RN6L-SW0m4Y-q_IzKf1BDJK5klDzqnCMt7adJPlXm3zAPGw"
GEMINI_MODEL = "gemini-3.8-flash"
COOKIE_SECURE = False  # Set True only when using HTTPS in production.

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    MAX_CONTENT_LENGTH=1_000_000,
)

DATA_DIR = os.getenv("RIO_DATA_DIR", "/tmp" if os.getenv("RENDER") else ".")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "rio_temporary.sqlite3")
MODEL = GEMINI_MODEL


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS guests (
                id INTEGER PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                guest_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(guest_id) REFERENCES guests(id)
            );
        """)
        connection.commit()


def current_guest(create=True):
    guest_id = session.get("rio_guest_id")
    if guest_id:
        with db() as connection:
            row = connection.execute(
                "SELECT id, token FROM guests WHERE id=?", (guest_id,)
            ).fetchone()
        if row:
            return row
        session.pop("rio_guest_id", None)

    if not create:
        return None

    token = secrets.token_urlsafe(32)
    with db() as connection:
        cursor = connection.execute(
            "INSERT INTO guests(token, created_at) VALUES(?, ?)",
            (token, now()),
        )
        connection.commit()
        guest_id = cursor.lastrowid

    session["rio_guest_id"] = guest_id
    with db() as connection:
        return connection.execute(
            "SELECT id, token FROM guests WHERE id=?", (guest_id,)
        ).fetchone()


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/")
def home():
    return render_template("landing.html")


@app.get("/app")
def workspace():
    guest = current_guest()
    with db() as connection:
        history = [
            dict(row)
            for row in connection.execute(
                "SELECT role, content FROM messages WHERE guest_id=? "
                "ORDER BY id DESC LIMIT 40",
                (guest["id"],),
            ).fetchall()
        ][::-1]
    return render_template(
        "app.html",
        user={"username": "زائر", "role": "writer"},
        history=history,
    )


@app.post("/api/chat")
def chat():
    guest = current_guest()
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()

    if not message:
        return jsonify(error="اكتب رسالة أولاً."), 400
    if len(message) > 6000:
        return jsonify(error="الرسالة أطول من الحد المسموح (6000 حرف)."), 413

    api_key = GEMINI_API_KEY.strip()
    if not api_key or api_key == "PASTE_NEW_GEMINI_API_KEY_HERE":
        return jsonify(
            error="أضف مفتاح Gemini الجديد في أعلى ملف app.py ثم أعد تشغيل RIO."
        ), 503

    with db() as connection:
        previous = connection.execute(
            "SELECT role, content FROM messages WHERE guest_id=? "
            "ORDER BY id DESC LIMIT 12",
            (guest["id"],),
        ).fetchall()[::-1]
        connection.execute(
            "INSERT INTO messages(guest_id, role, content, created_at) "
            "VALUES(?, 'user', ?, ?)",
            (guest["id"], message, now()),
        )
        connection.commit()

    conversation = [
        ("User: " if row["role"] == "user" else "RIO: ") + row["content"]
        for row in previous
    ]
    conversation.append("User: " + message)
    prompt = "\n\n".join(conversation)

    instructions = (
        "You are RIO, a warm, imaginative bilingual creative companion focused on novels, books, "
        "and storytelling. Reply in the same language as the user's latest message. Help with "
        "characters, relationships, plot, scenes, dialogue, worldbuilding, summaries, reading "
        "recommendations, and continuity. Be collaborative, expressive, and clear. Do not claim "
        "permanent memory beyond the conversation history provided."
    )

    try:
        client = genai.Client(api_key=api_key)
        # New Gemini authorization keys (often beginning with "AQ")
        # should use the Interactions API rather than GenerateContent.
        result = client.interactions.create(
            model=MODEL,
            input=prompt,
            system_instruction=instructions,
            generation_config={
                "temperature": 0.8,
                "max_output_tokens": 1200,
            },
        )
        answer = (getattr(result, "output_text", None) or "").strip()
        if not answer:
            answer = "لم يصلني رد نصي هذه المرة. جرّب صياغة سؤالك مرة أخرى."
    except Exception:
        app.logger.exception("Gemini request failed")
        return jsonify(
            error="تعذر الاتصال بـ Gemini. تحقق من المفتاح والحصة واسم النموذج في إعدادات RIO."
        ), 502

    with db() as connection:
        connection.execute(
            "INSERT INTO messages(guest_id, role, content, created_at) "
            "VALUES(?, 'assistant', ?, ?)",
            (guest["id"], answer, now()),
        )
        connection.commit()

    return jsonify(answer=answer)


@app.post("/api/clear")
def clear_chat():
    guest = current_guest()
    with db() as connection:
        connection.execute(
            "DELETE FROM messages WHERE guest_id=?", (guest["id"],)
        )
        connection.commit()
    return jsonify(ok=True)


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        service="RIO",
        model=MODEL,
        temporary_storage=True,
    )


init_db()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
