import os
import sqlite3
import secrets
from pathlib import Path
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template, session
from google import genai


# ============================================================
# Load .env locally, if present.
# Render uses its Dashboard Environment Variables instead.
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def load_local_env():
    if not ENV_FILE.is_file():
        return

    try:
        for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()

            if len(value) >= 2 and value[0] == value[-1]:
                if value[0] in ("'", '"'):
                    value = value[1:-1]

            # Existing system/Render variables take precedence.
            if name and name not in os.environ:
                os.environ[name] = value
    except OSError:
        pass


load_local_env()


# ============================================================
# Configuration
# ============================================================

SECRET_KEY = (
    os.getenv("RIO_SECRET_KEY")
    or os.getenv("SECRET_KEY")
    or secrets.token_hex(32)
)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

COOKIE_SECURE = os.getenv(
    "COOKIE_SECURE",
    "true" if os.getenv("RENDER") else "false",
).strip().lower() in ("1", "true", "yes", "on")

app = Flask(__name__)
app.secret_key = SECRET_KEY

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    MAX_CONTENT_LENGTH=1_000_000,
)

DATA_DIR = os.getenv(
    "RIO_DATA_DIR",
    "/tmp" if os.getenv("RENDER") else str(BASE_DIR),
)
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "rio_temporary.sqlite3")
MODEL = GEMINI_MODEL


# ============================================================
# Database
# ============================================================

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
                role TEXT NOT NULL
                    CHECK(role IN ('user', 'assistant')),
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
                "SELECT id, token FROM guests WHERE id = ?",
                (guest_id,),
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
            "SELECT id, token FROM guests WHERE id = ?",
            (guest_id,),
        ).fetchone()


# ============================================================
# Security headers
# ============================================================

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ============================================================
# Pages
# ============================================================

@app.get("/")
def home():
    return render_template("landing.html")


@app.get("/app")
def workspace():
    guest = current_guest()

    with db() as connection:
        rows = connection.execute(
            """
            SELECT role, content
            FROM messages
            WHERE guest_id = ?
            ORDER BY id DESC
            LIMIT 40
            """,
            (guest["id"],),
        ).fetchall()

    history = [dict(row) for row in rows][::-1]

    return render_template(
        "app.html",
        user={"username": "زائر", "role": "writer"},
        history=history,
    )


# ============================================================
# Gemini response
# ============================================================

def generate_rio_answer(api_key, prompt, instructions):
    client = genai.Client(api_key=api_key)

    # Google AI Studio authorization keys beginning with AQ.
    # Use the Interactions API for this key type.
    if api_key.startswith("AQ."):
        result = client.interactions.create(
            model=MODEL,
            input=prompt,
            system_instruction=instructions,
            generation_config={
                "temperature": 0.8,
                "max_output_tokens": 1200,
            },
        )

        return (getattr(result, "output_text", None) or "").strip()

    # Conventional Gemini API keys use GenerateContent.
    result = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config={
            "system_instruction": instructions,
            "temperature": 0.8,
            "max_output_tokens": 1200,
        },
    )

    return (getattr(result, "text", None) or "").strip()


# ============================================================
# Chat API
# ============================================================

@app.post("/api/chat")
def chat():
    guest = current_guest()
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()

    if not message:
        return jsonify(error="اكتب رسالة أولاً."), 400

    if len(message) > 6000:
        return jsonify(
            error="الرسالة أطول من الحد المسموح (6000 حرف)."
        ), 413

    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        return jsonify(
            error=(
                "مفتاح Gemini غير مضبوط. أضف GEMINI_API_KEY "
                "في إعدادات البيئة ثم أعد تشغيل التطبيق."
            )
        ), 503

    with db() as connection:
        previous = connection.execute(
            """
            SELECT role, content
            FROM messages
            WHERE guest_id = ?
            ORDER BY id DESC
            LIMIT 12
            """,
            (guest["id"],),
        ).fetchall()[::-1]

        connection.execute(
            """
            INSERT INTO messages(guest_id, role, content, created_at)
            VALUES(?, 'user', ?, ?)
            """,
            (guest["id"], message, now()),
        )
        connection.commit()

    conversation = [
        ("User: " if row["role"] == "user" else "RIO: ")
        + row["content"]
        for row in previous
    ]
    conversation.append("User: " + message)
    prompt = "\n\n".join(conversation)

    instructions = (
        "You are RIO, a warm, imaginative bilingual creative companion "
        "focused on novels, books, and storytelling. Reply in the same "
        "language as the user's latest message. Help with characters, "
        "relationships, plot, scenes, dialogue, worldbuilding, summaries, "
        "reading recommendations, and continuity. Be collaborative, "
        "expressive, and clear. Do not claim permanent memory beyond the "
        "conversation history provided."
    )

    try:
        answer = generate_rio_answer(
            api_key=api_key,
            prompt=prompt,
            instructions=instructions,
        )

        if not answer:
            answer = (
                "لم يصلني رد نصي هذه المرة. "
                "جرّب صياغة سؤالك مرة أخرى."
            )

    except Exception:
        # Never log the API key or its value.
        app.logger.exception("Gemini request failed")
        return jsonify(
            error=(
                "تعذر الاتصال بـ RIO. "
            )
        ), 502

    with db() as connection:
        connection.execute(
            """
            INSERT INTO messages(guest_id, role, content, created_at)
            VALUES(?, 'assistant', ?, ?)
            """,
            (guest["id"], answer, now()),
        )
        connection.commit()

    return jsonify(answer=answer)


# ============================================================
# Clear chat
# ============================================================

@app.post("/api/clear")
def clear_chat():
    guest = current_guest()

    with db() as connection:
        connection.execute(
            "DELETE FROM messages WHERE guest_id = ?",
            (guest["id"],),
        )
        connection.commit()

    return jsonify(ok=True)


# ============================================================
# Health check
# ============================================================

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
