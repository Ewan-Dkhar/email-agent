"""
Automated Test Suite for Outbound SMTP Email Dispatching.
Validates configuration resolution, STARTTLS and SSL pipelines, error handling,
and REST API approval endpoint.
"""

from unittest.mock import MagicMock, patch
import pytest
import smtplib
from app.config import AppSettings, ImapConfig, SmtpConfig
from app.tools.smtp_client import (
    SmtpClient,
    SmtpClientError,
    SmtpConfigurationError,
    SmtpAuthError,
    SmtpConnectionError,
)
from app.tools.email_skills import DraftEmailReplySkill
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db, init_db


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_agent_vault.db"
    monkeypatch.setattr("app.database.get_db_path", lambda custom_path=None: custom_path or test_db)
    init_db(test_db)
    yield


def test_smtp_configuration_validation():
    # 1. Missing host
    client = SmtpClient(config=SmtpConfig(host="", username="user@test.com", password="pwd"))
    with pytest.raises(SmtpConfigurationError, match="host"):
        client.validate_configuration()

    # 2. Missing username & no fallback
    client2 = SmtpClient(config=SmtpConfig(host="smtp.test.com", username="", password="pwd"))
    client2.imap_config = ImapConfig(username="", password="")
    with pytest.raises(SmtpConfigurationError, match="username"):
        client2.validate_configuration()

    # 3. Missing password & no fallback
    client3 = SmtpClient(config=SmtpConfig(host="smtp.test.com", username="user@test.com", password=""))
    client3.imap_config = ImapConfig(username="user@test.com", password="")
    with pytest.raises(SmtpConfigurationError, match="password"):
        client3.validate_configuration()


def test_smtp_fallback_to_imap_credentials():
    config = SmtpConfig(host="smtp.gmail.com", username="", password="", from_address="")
    client = SmtpClient(config=config)
    client.imap_config = ImapConfig(username="fallback@gmail.com", password="app_secret_pass")

    assert client.username == "fallback@gmail.com"
    assert client.password == "app_secret_pass"
    assert client.from_address == "fallback@gmail.com"


def test_smtp_send_starttls_success():
    config = SmtpConfig(
        host="smtp.mail.com",
        port=587,
        use_tls=True,
        use_ssl=False,
        username="sender@mail.com",
        password="secretpassword",
        from_address="sender@mail.com"
    )
    client = SmtpClient(config=config)

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        res = client.send_email(
            recipient="recipient@test.com",
            subject="Test Subject",
            body_text="Hello, this is a test email."
        )

        assert res["success"] is True
        assert res["recipient"] == "recipient@test.com"
        assert res["subject"] == "Test Subject"
        assert "message_id" in res

        mock_smtp_cls.assert_called_once_with(host="smtp.mail.com", port=587, timeout=30.0)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("sender@mail.com", "secretpassword")
        mock_server.send_message.assert_called_once()


def test_smtp_send_ssl_success():
    config = SmtpConfig(
        host="smtp.mail.com",
        port=465,
        use_ssl=True,
        username="sender@mail.com",
        password="secretpassword"
    )
    client = SmtpClient(config=config)

    with patch("smtplib.SMTP_SSL") as mock_ssl_cls:
        mock_server = MagicMock()
        mock_ssl_cls.return_value.__enter__.return_value = mock_server

        res = client.send_email(
            recipient="client@test.com",
            subject="SSL Subject",
            body_text="Body over SSL"
        )

        assert res["success"] is True
        mock_ssl_cls.assert_called_once()
        mock_server.login.assert_called_once_with("sender@mail.com", "secretpassword")
        mock_server.send_message.assert_called_once()


def test_smtp_auth_error_handling():
    client = SmtpClient(
        config=SmtpConfig(
            host="smtp.mail.com",
            port=587,
            username="baduser",
            password="wrongpassword"
        )
    )

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        with pytest.raises(SmtpAuthError, match="SMTP Authentication failed"):
            client.send_email("to@test.com", "Subject", "Body")


def test_smtp_connection_error_handling():
    client = SmtpClient(
        config=SmtpConfig(
            host="unreachable.host",
            port=587,
            username="user",
            password="pwd"
        )
    )

    with patch("smtplib.SMTP", side_effect=smtplib.SMTPConnectError(421, "Connection refused")):
        with pytest.raises(SmtpConnectionError, match="connection error"):
            client.send_email("to@test.com", "Subject", "Body")


@pytest.mark.asyncio
async def test_api_approve_and_send_draft():
    test_client = TestClient(app)

    # 1. Stage a test draft in memory
    draft_id = "test_draft_123"
    DraftEmailReplySkill._staged_drafts[draft_id] = {
        "draft_id": draft_id,
        "recipient": "prof@university.edu",
        "subject": "Re: Project Extension",
        "body_markdown": "Dear Professor, thank you for the extra time.",
        "status": "PENDING_APPROVAL"
    }

    # 2. Mock SMTP dispatch
    with patch("app.tools.smtp_client.SmtpClient.send_email") as mock_send:
        mock_send.return_value = {"success": True, "recipient": "prof@university.edu"}

        response = test_client.post(
            f"/api/drafts/{draft_id}/approve",
            json={
                "recipient": "prof@university.edu",
                "subject": "Re: Project Extension",
                "body_markdown": "Dear Professor, thank you for the extra time."
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["draft_id"] == draft_id
        assert data["status"] == "APPROVED"
        assert "successfully sent" in data["message"]

        mock_send.assert_called_once_with(
            "prof@university.edu",
            "Re: Project Extension",
            "Dear Professor, thank you for the extra time."
        )

        # 3. Verify SQLite audit log
        with get_db() as conn:
            row = conn.execute("SELECT * FROM sent_emails WHERE draft_id = ?", (draft_id,)).fetchone()
            assert row is not None
            assert row["recipient"] == "prof@university.edu"
            assert row["status"] == "SENT"


def test_api_approve_draft_smtp_failure():
    test_client = TestClient(app)

    draft_id = "failed_draft_456"
    DraftEmailReplySkill._staged_drafts[draft_id] = {
        "draft_id": draft_id,
        "recipient": "recipient@domain.com",
        "subject": "Hello",
        "body_markdown": "Content",
        "status": "PENDING_APPROVAL"
    }

    with patch("app.tools.smtp_client.SmtpClient.send_email", side_effect=SmtpClientError("Connection timed out")):
        response = test_client.post(f"/api/drafts/{draft_id}/approve")
        assert response.status_code == 502
        assert "SMTP Dispatch Failed" in response.json()["detail"]
