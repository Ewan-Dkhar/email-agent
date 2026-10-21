"""
Unit Tests for Ingestion, MIME Parsing, and Data Contracts.
"""

from email.message import EmailMessage
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from app.database import get_db, init_db
from app.ingestion.imap_client import ImapSyncClient
from app.ingestion.sanitizer import clean_html, parse_raw_email
from app.schemas import EmailTriageResult, ExtractedTask, PriorityTier, SanitizedEmail


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ingestion.db"
        init_db(db_path)
        yield db_path


def test_clean_html_strips_scripts_and_tracking_pixels():
    html_input = """
    <html>
      <head>
        <title>Notice</title>
        <script>console.log("malicious code");</script>
        <style>body { color: red; }</style>
      </head>
      <body>
        <h1>Academic Fee Deadline</h1>
        <p>Please pay your tuition before <strong>Friday at 5:00 PM</strong>.</p>
        <p><a href="https://portal.university.edu/pay">Payment Portal</a></p>
        <img src="https://tracker.com/pixel.gif" width="1" height="1" alt="tracker">
        <img src="data:image/png;base64,iVBORw0KGgoAAA..." alt="embedded">
      </body>
    </html>
    """
    cleaned = clean_html(html_input)

    assert "console.log" not in cleaned
    assert "body { color: red; }" not in cleaned
    assert "tracker.com" not in cleaned
    assert "data:image/png" not in cleaned
    assert "Academic Fee Deadline" in cleaned
    assert "[Payment Portal](https://portal.university.edu/pay)" in cleaned


def test_parse_raw_email_multipart():
    msg = EmailMessage()
    msg["From"] = "registrar@university.edu"
    msg["Subject"] = "Spring Registration"
    msg["Date"] = "Wed, 21 Oct 2026 10:00:00 +0000"

    html_content = """
    <div>
      <p>Click here to register: <a href="https://reg.edu/start">Registration Link</a></p>
    </div>
    """
    msg.add_alternative(html_content, subtype="html")

    raw_bytes = msg.as_bytes()
    sanitized: SanitizedEmail = parse_raw_email(raw_bytes, imap_uid="9999")

    assert sanitized.imap_uid == "9999"
    assert sanitized.sender == "registrar@university.edu"
    assert sanitized.subject == "Spring Registration"
    assert "[Registration Link](https://reg.edu/start)" in sanitized.cleaned_body
    assert len(sanitized.raw_snippet) > 0


def test_pydantic_schema_validation():
    # Valid extraction
    result = EmailTriageResult(
        is_actionable=True,
        tasks=[
            ExtractedTask(
                title="Pay Semester Fees",
                priority=PriorityTier.P1_CRITICAL,
                deadline="2026-10-23 17:00",
                summary="Pay remaining balance before late fee applies.",
                action_url="https://pay.edu",
            )
        ],
    )
    assert len(result.tasks) == 1
    assert result.tasks[0].priority == PriorityTier.P1_CRITICAL

    # JSON Schema generation
    schema = EmailTriageResult.model_json_schema()
    assert "properties" in schema
    assert "is_actionable" in schema["properties"]
    assert "tasks" in schema["properties"]


def test_imap_uid_deduplication(temp_db):
    # Pre-populate database with UID "101"
    with get_db(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO processed_emails (imap_uid, sender, subject, received_at, raw_snippet)
            VALUES ('101', 'sender@test.com', 'Old Email', '2026-10-20', 'Snippet')
            """
        )

    # Prepare raw email for UID 102
    msg = EmailMessage()
    msg["From"] = "advisor@test.com"
    msg["Subject"] = "New Advising Appointment"
    msg["Date"] = "2026-10-21"
    msg.set_content("Please schedule your advising call.")
    raw_102 = msg.as_bytes()

    client = ImapSyncClient()

    # Mock imaplib network socket calls
    mock_imap = MagicMock()
    # Server reports UIDs 101 and 102
    mock_imap.uid.side_effect = [
        ("OK", [b"101 102"]),                      # uid("search", ...)
        ("OK", [(b"1 (RFC822 {100}", raw_102)]),  # uid("fetch", "102", ...)
    ]

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        new_emails = client.fetch_unprocessed_emails(db_path=temp_db)

        # Only UID 102 should be fetched; UID 101 was already in SQLite
        assert len(new_emails) == 1
        assert new_emails[0].imap_uid == "102"
        assert new_emails[0].subject == "New Advising Appointment"

        # Verify UID 102 was saved to SQLite
        with get_db(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT imap_uid FROM processed_emails WHERE imap_uid = '102'")
            assert cursor.fetchone() is not None
