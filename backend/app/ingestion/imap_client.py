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

    def _get_max_processed_uid(self, db_path: Optional[Path] = None) -> Optional[int]:
        """Queries SQLite for the highest numerical IMAP UID processed so far."""
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(CAST(imap_uid AS INTEGER)) AS max_uid FROM processed_emails")
            row = cursor.fetchone()
            if row and row["max_uid"] is not None:
                return int(row["max_uid"])
            return None

    def _save_processed_email(self, email_data: SanitizedEmail, db_path: Optional[Path] = None) -> None:
        """Persists email metadata into processed_emails table with initial is_triaged = 0."""
        with get_db(db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO processed_emails (imap_uid, sender, subject, received_at, raw_snippet, is_triaged)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (
                    email_data.imap_uid,
                    email_data.sender,
                    email_data.subject,
                    email_data.received_at,
                    email_data.raw_snippet,
                )
            )

    def fetch_unprocessed_emails(
        self,
        mailbox: Optional[str] = None,
        max_emails: int = 50,
        db_path: Optional[Path] = None
    ) -> List[SanitizedEmail]:
        """
        Connects to IMAP server, queries new UIDs using High-Water Mark cursor tracking,
        fetches raw payloads, sanitizes them, and persists records into processed_emails.
        """
        if not self.config.username or not self.config.password:
            logger.warning("IMAP credentials not configured. Skipping remote fetch.")
            return []

        target_mailbox = mailbox or self.config.mailbox
        max_uid = self._get_max_processed_uid(db_path)
        new_emails: List[SanitizedEmail] = []

        try:
            if self.config.use_ssl:
                mail = imaplib.IMAP4_SSL(self.config.host, self.config.port)
            else:
                mail = imaplib.IMAP4(self.config.host, self.config.port)

            mail.login(self.config.username, self.config.password)
            mail.select(target_mailbox, readonly=True)

            if max_uid is not None:
                # High-Water Mark cursor search: only query messages with UID > max_uid
                search_criteria = f"UID {max_uid + 1}:*"
            else:
                # Bootstrap mode for fresh mailbox: query all
                search_criteria = "ALL"

            status, search_data = mail.uid("search", None, search_criteria)
            if status != "OK" or not search_data or not search_data[0]:
                mail.logout()
                return []

            server_uids = [uid.decode("utf-8") for uid in search_data[0].split()]

            # IMAP RFC 3501 boundary protection:
            # If search is 'UID X:*' and no UID >= X exists, some servers return the highest existing UID.
            # Strictly filter for UIDs greater than max_uid:
            if max_uid is not None:
                unprocessed_uids = [
                    uid for uid in server_uids
                    if uid.isdigit() and int(uid) > max_uid
                ]
            else:
                # On initial bootstrap, ingest most recent first capped at max_emails
                unprocessed_uids = server_uids[-max_emails:]

            # Cap batch size to avoid unbounded memory / network stalls
            unprocessed_uids = unprocessed_uids[:max_emails]

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
