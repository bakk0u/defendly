from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_DB = Path(__file__).resolve().parent / "data" / "interview_agent.db"


def database_path() -> Path:
    configured = os.getenv("DATABASE_PATH")
    path = Path(configured).expanduser() if configured else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(database_path(), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def init_database() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                preferred_provider TEXT NOT NULL DEFAULT 'ollama',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cvs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                source_name TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                extraction_json TEXT NOT NULL,
                model_used TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cv_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cv_id INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                technologies_json TEXT NOT NULL DEFAULT '[]',
                metrics_json TEXT NOT NULL DEFAULT '[]',
                claims_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS cv_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cv_id INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'technical',
                UNIQUE(cv_id, name, category)
            );
            CREATE TABLE IF NOT EXISTS cv_experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cv_id INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                period TEXT NOT NULL DEFAULT '',
                achievements_json TEXT NOT NULL DEFAULT '[]',
                technologies_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cv_id INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL,
                item_name TEXT NOT NULL,
                question TEXT NOT NULL,
                focus TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                answer TEXT NOT NULL,
                evaluation_json TEXT NOT NULL,
                score INTEGER NOT NULL,
                label TEXT NOT NULL,
                concept_coverage INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                cv_id INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS mastery_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                cv_id INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL,
                item_name TEXT NOT NULL,
                mastery REAL NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_questions_cv ON questions(cv_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_mastery_cv ON mastery_snapshots(cv_id, item_type, item_name);
            """
        )
        # Upgrade databases created by the original MVP without destroying local work.
        if "user_id" not in _columns(db, "cvs"):
            db.execute("ALTER TABLE cvs ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
        if "concept_coverage" not in _columns(db, "attempts"):
            db.execute("ALTER TABLE attempts ADD COLUMN concept_coverage INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cvs_user ON cvs(user_id, created_at DESC)")


def create_user(email: str, name: str, password_hash: str) -> sqlite3.Row:
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)",
            (email.strip().lower(), name.strip(), password_hash),
        )
        return db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()


def get_user_by_email(email: str) -> sqlite3.Row | None:
    with connection() as db:
        return db.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip(),)).fetchone()


def get_user(user_id: int) -> sqlite3.Row | None:
    with connection() as db:
        return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def update_user_provider(user_id: int, provider: str) -> sqlite3.Row:
    with connection() as db:
        db.execute(
            "UPDATE users SET preferred_provider = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (provider, user_id),
        )
        return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def save_cv(user_id: int, source_name: str, raw_text: str, extraction: dict, model_used: str) -> int:
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO cvs (user_id, source_name, raw_text, extraction_json, model_used) VALUES (?, ?, ?, ?, ?)",
            (user_id, source_name, raw_text, json.dumps(extraction), model_used),
        )
        cv_id = int(cursor.lastrowid)
        for project in extraction.get("projects", []):
            db.execute(
                "INSERT INTO cv_projects (cv_id, name, description, technologies_json, metrics_json, claims_json) VALUES (?, ?, ?, ?, ?, ?)",
                (cv_id, project["name"], project.get("description", ""), json.dumps(project.get("technologies", [])), json.dumps(project.get("metrics", [])), json.dumps(project.get("claims", []))),
            )
        for category, values in (("technical", extraction.get("technical_skills", [])), ("tool", extraction.get("tools_frameworks", []))):
            for value in values:
                db.execute("INSERT OR IGNORE INTO cv_skills (cv_id, name, category) VALUES (?, ?, ?)", (cv_id, value, category))
        for experience in extraction.get("work_experience", []):
            db.execute(
                "INSERT INTO cv_experiences (cv_id, company, role, period, achievements_json, technologies_json) VALUES (?, ?, ?, ?, ?, ?)",
                (cv_id, experience["company"], experience["role"], experience.get("period", ""), json.dumps(experience.get("achievements", [])), json.dumps(experience.get("technologies", []))),
            )
        return cv_id


def list_cvs(user_id: int) -> list[sqlite3.Row]:
    with connection() as db:
        return db.execute(
            """SELECT c.*, COUNT(DISTINCT p.id) AS project_count, COUNT(DISTINCT q.id) AS question_count
               FROM cvs c LEFT JOIN cv_projects p ON p.cv_id = c.id LEFT JOIN questions q ON q.cv_id = c.id
               WHERE c.user_id = ? GROUP BY c.id ORDER BY c.created_at DESC""",
            (user_id,),
        ).fetchall()


def get_cv(cv_id: int, user_id: int) -> sqlite3.Row | None:
    with connection() as db:
        return db.execute("SELECT * FROM cvs WHERE id = ? AND user_id = ?", (cv_id, user_id)).fetchone()


def save_questions(cv_id: int, questions: list[dict]) -> list[dict]:
    saved: list[dict] = []
    with connection() as db:
        for item in questions:
            cursor = db.execute(
                "INSERT INTO questions (cv_id, item_type, item_name, question, focus, difficulty) VALUES (?, ?, ?, ?, ?, ?)",
                (cv_id, item["item_type"], item["item_name"], item["question"], item["focus"], item["difficulty"]),
            )
            saved.append({**item, "id": int(cursor.lastrowid), "cv_id": cv_id})
    return saved


def get_question(question_id: int, user_id: int) -> sqlite3.Row | None:
    with connection() as db:
        return db.execute(
            "SELECT q.* FROM questions q JOIN cvs c ON c.id = q.cv_id WHERE q.id = ? AND c.user_id = ?",
            (question_id, user_id),
        ).fetchone()


def list_questions(cv_id: int, user_id: int) -> list[sqlite3.Row]:
    with connection() as db:
        return db.execute(
            "SELECT q.* FROM questions q JOIN cvs c ON c.id = q.cv_id WHERE q.cv_id = ? AND c.user_id = ? ORDER BY q.id",
            (cv_id, user_id),
        ).fetchall()


def save_attempt(question_id: int, answer: str, evaluation: dict) -> int:
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO attempts (question_id, answer, evaluation_json, score, label, concept_coverage) VALUES (?, ?, ?, ?, ?, ?)",
            (question_id, answer, json.dumps(evaluation), evaluation["score"], evaluation["label"], evaluation.get("concept_coverage", 0)),
        )
        return int(cursor.lastrowid)


def dashboard_rows(cv_id: int, user_id: int) -> list[sqlite3.Row]:
    with connection() as db:
        return db.execute(
            """SELECT q.item_type, q.item_name, q.id AS question_id, q.difficulty,
                      a.score, a.label, a.concept_coverage, a.created_at
               FROM questions q JOIN cvs c ON c.id = q.cv_id
               LEFT JOIN attempts a ON a.id = (
                   SELECT a2.id FROM attempts a2 WHERE a2.question_id = q.id ORDER BY a2.id DESC LIMIT 1
               )
               WHERE q.cv_id = ? AND c.user_id = ? ORDER BY q.item_type, q.item_name, q.id""",
            (cv_id, user_id),
        ).fetchall()


def create_chat_session(user_id: int, cv_id: int, provider: str) -> int:
    with connection() as db:
        cursor = db.execute("INSERT INTO chat_sessions (user_id, cv_id, provider) VALUES (?, ?, ?)", (user_id, cv_id, provider))
        return int(cursor.lastrowid)


def save_chat_message(session_id: int, role: str, content: str, metadata: dict | None = None) -> int:
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO chat_messages (session_id, role, content, metadata_json) VALUES (?, ?, ?, ?)",
            (session_id, role, content, json.dumps(metadata or {})),
        )
        return int(cursor.lastrowid)


def save_mastery(user_id: int, cv_id: int, item_type: str, item_name: str, mastery: float, confidence: float) -> None:
    with connection() as db:
        db.execute(
            "INSERT INTO mastery_snapshots (user_id, cv_id, item_type, item_name, mastery, confidence) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, cv_id, item_type, item_name, mastery, confidence),
        )
