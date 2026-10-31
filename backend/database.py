import contextlib
import sqlite3
import json
import os
import time
import uuid
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemos.db")
K_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "k.txt")

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are a helpful personal assistant and senior software engineer running inside GemOS (CTos v4.2). "
    "You help with general chat, coding questions, system architecture, debugging, explaining concepts, "
    "and everyday tasks. Give clear, concise, and practical answers. When sharing code, always use "
    "proper markdown code blocks with language identifiers. Ask yourself: do I need to write this line "
    "of excess code or can I use a cleaner, more idiomatic way?"
)

DEFAULT_PERSONAS = [
    {
        "id": "default",
        "name": "GemOS Core",
        "icon": "terminal",
        "description": "Balanced assistant for coding, architecture, and daily tasks",
        "prompt": DEFAULT_SYSTEM_INSTRUCTION,
    },
    {
        "id": "ctos_op",
        "name": "DedSec / CTos Operator",
        "icon": "shield",
        "description": "Cybersecurity, systems engineering, & tactical code analysis",
        "prompt": (
            "You are CTos Tactical AI, an elite systems & security engineering assistant developed at Blume / DedSec. "
            "Provide sharp, deeply technical, security-conscious answers. Prioritize performance, memory safety, "
            "clean architecture, and zero-bloat implementations. Use markdown code blocks with language tags."
        ),
    },
    {
        "id": "architect",
        "name": "Principal Architect",
        "icon": "cpu",
        "description": "Production-grade distributed systems & clean code review",
        "prompt": (
            "You are a Principal Staff Software Engineer. Review code and answer questions with an emphasis on "
            "scalability, maintainability, edge cases, complexity trade-offs, and production readiness. "
            "Provide concrete, runnable code examples without filler."
        ),
    },
    {
        "id": "concise",
        "name": "Zero-Fluff Code Only",
        "icon": "zap",
        "description": "Minimal explanation, direct code and immediate solutions",
        "prompt": (
            "Respond with minimal prose. Give the exact code or command needed first, followed by at most "
            "2-3 bullet points if critical context is required."
        ),
    },
]


def clean_api_key(raw: str) -> str:
    if not raw:
        return ""
    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        return ""
    key = lines[0]
    if "=" in key and "GEMINI_API_KEY" in key:
        key = key.split("=", 1)[1].strip()
    return key.strip("'\" \t\r\n")


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    model TEXT NOT NULL,
                    system_instruction TEXT NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT 'default',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    top_p REAL NOT NULL DEFAULT 0.95,
                    max_output_tokens INTEGER NOT NULL DEFAULT 8192,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
                """
            )

        # Initialize defaults if not present
        if not self.get_setting("model"):
            self.set_setting("model", "gemini-4-argon")
        if not self.get_setting("theme"):
            self.set_setting("theme", "ctos-dark")
        if not self.get_setting("system_instruction"):
            self.set_setting("system_instruction", DEFAULT_SYSTEM_INSTRUCTION)
        if not self.get_setting("temperature"):
            self.set_setting("temperature", "0.7")
        if not self.get_setting("top_p"):
            self.set_setting("top_p", "0.95")
        if not self.get_setting("max_output_tokens"):
            self.set_setting("max_output_tokens", "8192")

        # Load API key from env or k.txt if not stored in DB
        stored_key = self.get_setting("api_key")
        if not stored_key:
            env_key = clean_api_key(os.environ.get("GEMINI_API_KEY", ""))
            if env_key:
                self.set_setting("api_key", env_key)
            elif os.path.exists(K_PATH):
                try:
                    with open(K_PATH, "r", encoding="utf-8") as f:
                        file_key = clean_api_key(f.read())
                        if file_key:
                            self.set_setting("api_key", file_key)
                except Exception:
                    pass

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
        if key == "api_key" and value and self.db_path == DB_PATH:
            try:
                with open(K_PATH, "w", encoding="utf-8") as f:
                    f.write(value)
            except Exception:
                pass

    def get_all_settings(self) -> Dict[str, Any]:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            data = {r["key"]: r["value"] for r in rows}
        api_key = data.get("api_key", "")
        masked_key = ""
        if api_key:
            if len(api_key) > 10:
                masked_key = api_key[:4] + "•" * (len(api_key) - 8) + api_key[-4:]
            else:
                masked_key = "•" * len(api_key)
        return {
            "has_api_key": bool(api_key),
            "masked_api_key": masked_key,
            "model": data.get("model", "gemini-2.5-flash"),
            "theme": data.get("theme", "ctos-dark"),
            "system_instruction": data.get("system_instruction", DEFAULT_SYSTEM_INSTRUCTION),
            "temperature": float(data.get("temperature", 0.7)),
            "top_p": float(data.get("top_p", 0.95)),
            "max_output_tokens": int(data.get("max_output_tokens", 8192)),
            "personas": DEFAULT_PERSONAS,
        }

    # --- Sessions ---
    def list_sessions(self, query: str = "") -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if query.strip():
                q = f"%{query.strip()}%"
                rows = conn.execute(
                    """
                    SELECT DISTINCT s.*,
                        (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,
                        (SELECT substr(m.content, 1, 120) FROM messages m WHERE m.session_id = s.id ORDER BY m.created_at DESC LIMIT 1) AS last_preview
                    FROM sessions s
                    LEFT JOIN messages m ON m.session_id = s.id
                    WHERE s.title LIKE ? OR m.content LIKE ?
                    ORDER BY s.pinned DESC, s.updated_at DESC
                    """,
                    (q, q),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.*,
                        (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,
                        (SELECT substr(m.content, 1, 120) FROM messages m WHERE m.session_id = s.id ORDER BY m.created_at DESC LIMIT 1) AS last_preview
                    FROM sessions s
                    ORDER BY s.pinned DESC, s.updated_at DESC
                    """
                ).fetchall()
            return [dict(r) for r in rows]

    def create_session(
        self,
        title: str = "New Operation",
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        persona_id: str = "default",
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        sid = str(uuid.uuid4())
        model = model or self.get_setting("model", "gemini-2.5-flash")
        if system_instruction is None:
            for p in DEFAULT_PERSONAS:
                if p["id"] == persona_id:
                    system_instruction = p["prompt"]
                    break
            if not system_instruction:
                system_instruction = self.get_setting("system_instruction", DEFAULT_SYSTEM_INSTRUCTION)
        temperature = temperature if temperature is not None else float(self.get_setting("temperature", "0.7"))
        top_p = top_p if top_p is not None else float(self.get_setting("top_p", "0.95"))
        max_output_tokens = (
            max_output_tokens
            if max_output_tokens is not None
            else int(self.get_setting("max_output_tokens", "8192"))
        )

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    id, title, model, system_instruction, persona_id,
                    temperature, top_p, max_output_tokens, pinned, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    sid,
                    title,
                    model,
                    system_instruction,
                    persona_id,
                    temperature,
                    top_p,
                    max_output_tokens,
                    now,
                    now,
                ),
            )
        return self.get_session(sid)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            session = dict(row)
            msgs = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
            session["messages"] = [
                {
                    "id": m["id"],
                    "session_id": m["session_id"],
                    "role": m["role"],
                    "content": m["content"],
                    "attachments": json.loads(m["attachments_json"] or "[]"),
                    "metadata": json.loads(m["metadata_json"] or "{}"),
                    "created_at": m["created_at"],
                }
                for m in msgs
            ]
            return session

    def update_session(self, session_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        allowed = {
            "title",
            "model",
            "system_instruction",
            "persona_id",
            "temperature",
            "top_p",
            "max_output_tokens",
            "pinned",
        }
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not fields:
            return self.get_session(session_id)
        fields["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [session_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", values)
        return self.get_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cur.rowcount > 0

    def clear_session_messages(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time(), session_id))
        return self.get_session(session_id)

    # --- Messages ---
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        mid = str(uuid.uuid4())
        attachments = attachments or []
        metadata = metadata or {}
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO messages (id, session_id, role, content, attachments_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    session_id,
                    role,
                    content,
                    json.dumps(attachments),
                    json.dumps(metadata),
                    now,
                ),
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return {
            "id": mid,
            "session_id": session_id,
            "role": role,
            "content": content,
            "attachments": attachments,
            "metadata": metadata,
            "created_at": now,
        }

    def delete_messages_from(self, session_id: str, message_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT created_at FROM messages WHERE id = ? AND session_id = ?",
                (message_id, session_id),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "DELETE FROM messages WHERE session_id = ? AND created_at >= ?",
                (session_id, row["created_at"]),
            )
            return True
