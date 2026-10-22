"""
Triage Service Pipeline.
Coordinates prompt assembly, local inference, and database persistence.
"""

from datetime import datetime
import logging
from pathlib import Path
from typing import List, Optional
from app.database import get_db
from app.harness.ollama_client import OllamaClient
from app.harness.prompt_builder import build_triage_messages
from app.schemas import EmailTriageResult, ExtractedTask, SanitizedEmail

logger = logging.getLogger(__name__)


class TriageService:
    def __init__(self, ollama_client: Optional[OllamaClient] = None):
        self.ollama = ollama_client or OllamaClient()

    def _is_already_triaged(self, email_uid: str, db_path: Optional[Path] = None) -> bool:
        """Checks if an email UID has already been triaged by checking is_triaged or existing tasks."""
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT is_triaged FROM processed_emails WHERE imap_uid = ?",
                (email_uid,)
            )
            row = cursor.fetchone()
            if row and row["is_triaged"] == 1:
                return True
            cursor.execute("SELECT 1 FROM tasks WHERE email_uid = ? LIMIT 1", (email_uid,))
            return cursor.fetchone() is not None

    def _mark_as_triaged(self, email_uid: str, db_path: Optional[Path] = None) -> None:
        """Marks email as triaged in processed_emails table."""
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE processed_emails SET is_triaged = 1 WHERE imap_uid = ?",
                (email_uid,)
            )

    async def triage_and_persist(
        self,
        email_data: SanitizedEmail,
        reference_time: Optional[datetime] = None,
        db_path: Optional[Path] = None
    ) -> EmailTriageResult:
        """
        Executes end-to-end triage for a sanitized email:
        1. Checks idempotency guard to prevent duplicate Ollama inference.
        2. Builds grounded prompt with temporal anchor.
        3. Queries Ollama with grammar-constrained JSON decoding.
        4. Persists extracted tasks into SQLite tasks table.
        5. Marks email as triaged in processed_emails table.
        """
        if self._is_already_triaged(email_data.imap_uid, db_path=db_path):
            logger.info(f"Skipping email UID {email_data.imap_uid} - already triaged.")
            return EmailTriageResult(
                is_actionable=False,
                tasks=[]
            )

        messages = build_triage_messages(email_data, reference_time=reference_time)
        triage_result = await self.ollama.triage_email(messages)

        if triage_result.is_actionable and triage_result.tasks:
            self._save_tasks(email_data.imap_uid, triage_result.tasks, db_path=db_path)

        self._mark_as_triaged(email_data.imap_uid, db_path=db_path)

        return triage_result

    def _save_tasks(
        self,
        email_uid: str,
        tasks: List[ExtractedTask],
        db_path: Optional[Path] = None
    ) -> None:
        """
        Inserts extracted tasks into SQLite tasks table.
        Uses WAL mode and adheres to foreign key constraints with processed_emails.
        """
        with get_db(db_path) as conn:
            for task in tasks:
                conn.execute(
                    """
                    INSERT INTO tasks (email_uid, title, deadline, priority_tier, summary, action_url, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        email_uid,
                        task.title,
                        task.deadline,
                        task.priority.value,
                        task.summary,
                        task.action_url,
                    )
                )
            logger.info(f"Persisted {len(tasks)} tasks for email UID: {email_uid}")
