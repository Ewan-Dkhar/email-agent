"""
Unit Tests for Database Persistence Layer.
Verifies WAL mode, foreign key cascades, check constraints, and schema invariants.
"""

import sqlite3
import pytest
from pathlib import Path
import tempfile
from app.database import get_db, init_db, create_connection


@pytest.fixture
def temp_db():
    """Provides an isolated temporary database for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_agent_vault.db"
        init_db(db_path)
        yield db_path


def test_pragmas_configured(temp_db):
    """Verifies that WAL mode, normal synchronous, and foreign keys are active."""
    with get_db(temp_db) as conn:
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0].lower()
        assert journal_mode == "wal", f"Expected WAL mode, got {journal_mode}"

        cursor.execute("PRAGMA synchronous;")
        sync_mode = cursor.fetchone()[0]
        # 1 corresponds to NORMAL in SQLite
        assert sync_mode == 1, f"Expected synchronous=NORMAL (1), got {sync_mode}"

        cursor.execute("PRAGMA foreign_keys;")
        fk = cursor.fetchone()[0]
        assert fk == 1, f"Expected foreign_keys=ON (1), got {fk}"


def test_insert_and_query_email_and_task(temp_db):
    """Verifies basic insert, relational linkage, and query."""
    with get_db(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO processed_emails (imap_uid, sender, subject, received_at, raw_snippet)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("1001", "registrar@university.edu", "Spring Course Registration Deadline", "2026-10-21 09:00", "Snippet")
        )
        conn.execute(
            """
            INSERT INTO tasks (email_uid, title, deadline, priority_tier, summary, action_url, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("1001", "Register for Spring Electives", "2026-10-25 17:00", "P1_CRITICAL", "Select courses before window closes", "https://portal.university.edu", "PENDING")
        )

    with get_db(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.title, t.priority_tier, e.sender
            FROM tasks t
            JOIN processed_emails e ON t.email_uid = e.imap_uid
            WHERE t.email_uid = ?
            """,
            ("1001",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["title"] == "Register for Spring Electives"
        assert row["priority_tier"] == "P1_CRITICAL"
        assert row["sender"] == "registrar@university.edu"


def test_foreign_key_violation_rejected(temp_db):
    """Verifies that inserting a task referencing a non-existent email_uid fails."""
    with pytest.raises(sqlite3.IntegrityError):
        with get_db(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO tasks (email_uid, title, priority_tier, summary, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("NON_EXISTENT_UID", "Orphan Task", "P2_ACTIONABLE", "No parent email", "PENDING")
            )


def test_cascade_delete(temp_db):
    """Verifies that deleting a processed_email cascades to tasks and execution_logs."""
    with get_db(temp_db) as conn:
        conn.execute(
            "INSERT INTO processed_emails (imap_uid, sender, subject, received_at) VALUES (?, ?, ?, ?)",
            ("2002", "prof@university.edu", "Homework 3 Released", "2026-10-21 10:00")
        )
        cursor = conn.execute(
            """
            INSERT INTO tasks (email_uid, title, priority_tier, summary, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("2002", "Submit HW3", "P2_ACTIONABLE", "Complete by Tuesday", "PENDING")
        )
        task_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO execution_logs (task_id, tool_name, tool_input, tool_output)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, "read_local_file", "{}", "{}")
        )

    # Delete the parent email
    with get_db(temp_db) as conn:
        conn.execute("DELETE FROM processed_emails WHERE imap_uid = ?", ("2002",))

    # Verify task and execution log are deleted
    with get_db(temp_db) as conn:
        t_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE email_uid = ?", ("2002",)).fetchone()[0]
        l_count = conn.execute("SELECT COUNT(*) FROM execution_logs WHERE task_id = ?", (task_id,)).fetchone()[0]
        assert t_count == 0, "Task was not deleted on cascade"
        assert l_count == 0, "Execution log was not deleted on cascade"


def test_check_constraints(temp_db):
    """Verifies check constraints on priority_tier and status."""
    with get_db(temp_db) as conn:
        conn.execute(
            "INSERT INTO processed_emails (imap_uid, sender, subject, received_at) VALUES (?, ?, ?, ?)",
            ("3003", "sender@test.com", "Test", "2026-10-21")
        )

    # Invalid priority_tier
    with pytest.raises(sqlite3.IntegrityError):
        with get_db(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO tasks (email_uid, title, priority_tier, summary)
                VALUES (?, ?, ?, ?)
                """,
                ("3003", "Task", "INVALID_PRIORITY", "Summary")
            )

    # Invalid status
    with pytest.raises(sqlite3.IntegrityError):
        with get_db(temp_db) as conn:
            conn.execute(
                """
                INSERT INTO tasks (email_uid, title, priority_tier, summary, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("3003", "Task", "P1_CRITICAL", "Summary", "UNKNOWN_STATUS")
            )
