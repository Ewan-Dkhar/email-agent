"""
Database Connection & Persistence Manager.
Implements SQLite3 in WAL mode with Foreign Keys enabled and schema initialization.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional
from app.config import get_settings

DDL_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS processed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imap_uid TEXT UNIQUE NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    raw_snippet TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_uid TEXT NOT NULL,
    title TEXT NOT NULL,
    deadline TEXT, -- ISO 8601 (YYYY-MM-DD HH:MM) or NULL
    priority_tier TEXT NOT NULL CHECK(priority_tier IN ('P1_CRITICAL', 'P2_ACTIONABLE', 'P3_INFORMATIONAL')),
    summary TEXT NOT NULL,
    action_url TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'DISMISSED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (email_uid) REFERENCES processed_emails(imap_uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    thought TEXT,
    tool_name TEXT NOT NULL,
    tool_input TEXT NOT NULL, -- JSON string
    tool_output TEXT NOT NULL, -- JSON string
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_priority_status ON tasks(priority_tier, status);
CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks(deadline);
CREATE INDEX IF NOT EXISTS idx_emails_uid ON processed_emails(imap_uid);
"""


def get_db_path(custom_path: Optional[Path] = None) -> Path:
    """Returns the resolved SQLite database path."""
    if custom_path:
        return custom_path
    settings = get_settings()
    backend_root = Path(__file__).resolve().parent.parent
    return settings.database.resolved_path(backend_root)


def create_connection(db_path: Path) -> sqlite3.Connection:
    """
    Creates and configures a new SQLite connection.
    Enforces foreign keys, WAL pragma, and busy timeout for concurrent access.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=30.0, # 30s busy timeout before raising OperationalError
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    # Critical SQLite Pragmas must be set on every connection:
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


@contextmanager
def get_db(custom_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for database transactions.
    Automatically commits on success or rolls back on unhandled exceptions.
    """
    db_path = get_db_path(custom_path)
    conn = create_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(custom_path: Optional[Path] = None) -> None:
    """
    Executes the DDL schema to initialize or migrate the database structure.
    """
    db_path = get_db_path(custom_path)
    with get_db(db_path) as conn:
        conn.executescript(DDL_SCHEMA)
