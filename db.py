"""
db.py
SQLite persistence: per-Telegram-user profile (risk, goals) + rolling chat history
so the agent remembers context across messages and restarts.
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "sip_agent.db"))


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id     TEXT PRIMARY KEY,
                name        TEXT,
                risk        TEXT,
                profile_json TEXT,
                updated_at  TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   TEXT,
                role      TEXT,
                content   TEXT,
                created_at TEXT
            )""")


def save_profile(user_id: str, **fields):
    existing = get_profile(user_id) or {}
    existing.update({k: v for k, v in fields.items() if v is not None})
    with _conn() as c:
        c.execute(
            """INSERT INTO profiles (user_id, name, risk, profile_json, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 name=excluded.name, risk=excluded.risk,
                 profile_json=excluded.profile_json, updated_at=excluded.updated_at""",
            (user_id, existing.get("name"), existing.get("risk"),
             json.dumps(existing), datetime.utcnow().isoformat()),
        )
    return existing


def get_profile(user_id: str):
    with _conn() as c:
        row = c.execute("SELECT profile_json FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return json.loads(row["profile_json"]) if row and row["profile_json"] else None


def add_message(user_id: str, role: str, content: str):
    with _conn() as c:
        c.execute("INSERT INTO history (user_id, role, content, created_at) VALUES (?,?,?,?)",
                  (user_id, role, content, datetime.utcnow().isoformat()))


def get_recent_messages(user_id: str, limit: int = 20):
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_user(user_id: str):
    with _conn() as c:
        c.execute("DELETE FROM history WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM profiles WHERE user_id=?", (user_id,))
