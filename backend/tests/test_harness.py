"""
Unit Tests for Local Inference Harness, Prompt Builder, and Triage Pipeline.
"""

from datetime import datetime
import json
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from app.database import get_db, init_db
from app.harness.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaModelNotFoundError,
)
from app.harness.prompt_builder import build_triage_messages
from app.harness.triage_service import TriageService
from app.schemas import EmailTriageResult, ExtractedTask, PriorityTier, SanitizedEmail


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_harness.db"
        init_db(db_path)
        yield db_path


def test_prompt_builder_temporal_anchoring_and_boundary():
    email_data = SanitizedEmail(
        imap_uid="7007",
        sender="bursar@university.edu",
        subject="Tuition Overdue Notice",
        received_at="Wed, 21 Oct 2026 12:00:00 +0000",
        cleaned_body="Please settle balance by Friday at 5:00 PM.",
        raw_snippet="Please settle balance by Friday at 5:00 PM."
    )

    fixed_time = datetime(2026, 10, 21, 14, 30, 0) # Wednesday
    messages = build_triage_messages(email_data, reference_time=fixed_time)

    assert len(messages) == 2
    system_msg = messages[0]["content"]
    user_msg = messages[1]["content"]

    # Verify temporal anchor was dynamically injected
    assert "2026-10-21 14:30:00" in system_msg
    assert "Wednesday" in system_msg

    # Verify security boundary tags enclose untrusted content
    assert "<untrusted_email_data>" in user_msg
    assert "</untrusted_email_data>" in user_msg
    assert "Please settle balance by Friday at 5:00 PM." in user_msg
    assert "bursar@university.edu" in user_msg


@pytest.mark.asyncio
async def test_ollama_client_health_check_success():
    client = OllamaClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [{"name": "gemma2:9b"}, {"name": "llama3:latest"}]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        health = await client.check_health()
        assert health["online"] is True
        assert health["model_installed"] is True
        assert "gemma2:9b" in health["available_models"]


@pytest.mark.asyncio
async def test_ollama_client_connection_error():
    client = OllamaClient()

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(OllamaConnectionError):
            await client.check_health()


@pytest.mark.asyncio
async def test_ollama_client_model_not_found():
    client = OllamaClient()
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(OllamaModelNotFoundError):
            await client.triage_email([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_triage_service_end_to_end_persistence(temp_db):
    # 1. Pre-insert email into processed_emails to satisfy Foreign Key
    with get_db(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO processed_emails (imap_uid, sender, subject, received_at, raw_snippet)
            VALUES ('5005', 'dean@university.edu', 'Degree Application Deadline', '2026-10-21', 'Snippet')
            """
        )

    # 2. Mock Ollama response with grammar-compliant JSON
    mock_llm_result = {
        "is_actionable": True,
        "tasks": [
            {
                "title": "Submit Graduation Application",
                "priority": "P1_CRITICAL",
                "deadline": "2026-10-23 17:00",
                "summary": "Must submit graduation paperwork before Friday deadline.",
                "action_url": "https://portal.university.edu/grad"
            }
        ]
    }

    mock_ollama_client = MagicMock(spec=OllamaClient)
    mock_ollama_client.triage_email = AsyncMock(
        return_value=EmailTriageResult.model_validate(mock_llm_result)
    )

    # 3. Execute triage pipeline
    email_data = SanitizedEmail(
        imap_uid="5005",
        sender="dean@university.edu",
        subject="Degree Application Deadline",
        received_at="2026-10-21",
        cleaned_body="Apply before Friday at [Grad Portal](https://portal.university.edu/grad)",
        raw_snippet="Apply before Friday"
    )

    service = TriageService(ollama_client=mock_ollama_client)
    result = await service.triage_and_persist(email_data, db_path=temp_db)

    assert result.is_actionable is True
    assert len(result.tasks) == 1

    # 4. Verify task was persisted in SQLite
    with get_db(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE email_uid = '5005'")
        task_row = cursor.fetchone()
        assert task_row is not None
        assert task_row["title"] == "Submit Graduation Application"
        assert task_row["priority_tier"] == "P1_CRITICAL"
        assert task_row["deadline"] == "2026-10-23 17:00"
        assert task_row["status"] == "PENDING"
        assert task_row["action_url"] == "https://portal.university.edu/grad"

    # 5. Call triage_and_persist a second time to verify idempotency guard
    mock_ollama_client.triage_email.reset_mock()
    repeat_result = await service.triage_and_persist(email_data, db_path=temp_db)

    # Verify Ollama was NOT called again
    mock_ollama_client.triage_email.assert_not_called()
    assert repeat_result.is_actionable is False
    assert len(repeat_result.tasks) == 0

    # Verify task count in database remains exactly 1 (no duplicate rows)
    with get_db(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE email_uid = '5005'")
        assert cursor.fetchone()[0] == 1

