"""
IMAP Ingestion Client.
Manages secure IMAP4_SSL connection, UID tracking, and incremental email fetching.
"""

import imaplib
import logging
from typing import List, Set, Optional
from pathlib import Path
from app.config import ImapConfig, get_settings
from app.database import get_db
from app.ingestion.sanitizer import parse_raw_email
from app.schemas import SanitizedEmail

logger = logging.getLogger(__name__)


class ImapSyncClient:
    def __init__(self, config: Optional[ImapConfig] = None):
        self.config = config or get_settings().imap

    def _get_processed_uids(self, db_path: Optional[Path] = None) -> Set[str]:
        """Queries SQLite for previously ingested IMAP UIDs."""
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT imap_uid FROM processed_emails")
            return {row["imap_uid"] for row in cursor.fetchall()}

    def _save_processed_email(self, email_data: SanitizedEmail, db_path: Optional[Path] = None) -> None:
        """Persists email metadata into processed_emails table."""
        with get_db(db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO processed_emails (imap_uid, sender, subject, received_at, raw_snippet)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    email_data.imap_uid,
                    email_data.sender,
                    email_data.subject,
                    email_data.received_at,
                    email_data.raw_snippet
                )
            )

    def fetch_unprocessed_emails(
        self,
        mailbox: Optional[str] = None,
        max_emails: int = 50,
        db_path: Optional[Path] = None
    ) -> List[SanitizedEmail]:
        """
        Connects to IMAP server, identifies new UIDs not in SQLite,
        fetches raw payloads, sanitizes them, and persists records.
        """
        if not self.config.username or not self.config.password:
            logger.warning("IMAP credentials not configured. Skipping remote fetch.")
            return []

        target_mailbox = mailbox or self.config.mailbox
        processed_uids = self._get_processed_uids(db_path)
        new_emails: List[SanitizedEmail] = []

        try:
            if self.config.use_ssl:
                mail = imaplib.IMAP4_SSL(self.config.host, self.config.port)
            else:
                mail = imaplib.IMAP4(self.config.host, self.config.port)

            mail.login(self.config.username, self.config.password)
            mail.select(target_mailbox, readonly=True)

            # Search for all message UIDs in the mailbox
            status, search_data = mail.uid("search", None, "ALL")
            if status != "OK" or not search_data or not search_data[0]:
                mail.logout()
                return []

            server_uids = [uid.decode("utf-8") for uid in search_data[0].split()]
            unprocessed_uids = [uid for uid in server_uids if uid not in processed_uids]

            # Ingest most recent first, capped at max_emails per poll
            unprocessed_uids = unprocessed_uids[-max_emails:]

            for uid in unprocessed_uids:
                status, fetch_data = mail.uid("fetch", uid, "(RFC822)")
                if status != "OK" or not fetch_data:
                    continue

                for response_part in fetch_data:
                    if isinstance(response_part, tuple) and len(response_part) >= 2:
                        raw_bytes = response_part[1]
                        sanitized = parse_raw_email(raw_bytes, imap_uid=uid)
                        self._save_processed_email(sanitized, db_path)
                        new_emails.append(sanitized)

            mail.close()
            mail.logout()
        except Exception as e:
            logger.error(f"IMAP fetch failure: {str(e)}")
            raise

        return new_emails
