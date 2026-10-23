"""
Unit and Integration Tests for FastAPI REST Endpoints.
Verifies task querying, status updates, agent co-pilot triggers, and draft approval gates.
"""

from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from app.database import get_db, init_db
from app.harness.agent_loop import AgentLoopResult
from app.main import app
from app.tools.email_skills import DraftEmailReplySkill


@pytest.fixture
def temp_db(monkeypatch):
    """Sets up an isolated SQLite test database and patches get_db_path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_api.db"
        init_db(db_path)

        # Patch get_db default path in main module
        monkeypatch.setattr("app.database.get_db_path", lambda custom_path=None: custom_path or db_path)

        # Seed initial email and tasks
        with get_db(db_path) as conn:
            conn.execute(
                """
                INSERT INTO processed_emails (imap_uid, sender, subject, received_at, raw_snippet)
                VALUES ('1001', 'bursar@university.edu', 'Tuition Bill', '2026-10-22', 'Snippet')
                """
            )
            conn.execute(
                """
                INSERT INTO tasks (id, email_uid, title, deadline, priority_tier, summary, action_url, status)
                VALUES (1, '1001', 'Pay Semester Tuition', '2026-10-24 17:00', 'P1_CRITICAL', 'Pay fees', 'https://portal.edu/pay', 'PENDING')
                """
            )
            conn.execute(
                """
                INSERT INTO tasks (id, email_uid, title, deadline, priority_tier, summary, action_url, status)
                VALUES (2, '1001', 'Review Campus Notice', NULL, 'P3_INFORMATIONAL', 'General update', NULL, 'COMPLETED')
                """
            )
            conn.execute(
                """
                INSERT INTO execution_logs (task_id, thought, tool_name, tool_input, tool_output)
                VALUES (1, 'Inspecting bill', 'read_local_file', '{"relative_path": "bill.txt"}', '{"success": true}')
                """
            )

        yield db_path


@pytest.mark.asyncio
async def test_health_endpoint(temp_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "WAL mode" in data["database"]
        assert "ollama" in data


@pytest.mark.asyncio
async def test_list_tasks_and_filtering(temp_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch all tasks
        all_res = await client.get("/api/tasks")
        assert all_res.status_code == 200
        all_tasks = all_res.json()
        assert len(all_tasks) == 2

        # 2. Filter by status=PENDING
        pending_res = await client.get("/api/tasks?status=PENDING")
        assert pending_res.status_code == 200
        pending_tasks = pending_res.json()
        assert len(pending_tasks) == 1
        assert pending_tasks[0]["title"] == "Pay Semester Tuition"

        # 3. Filter by priority=P3_INFORMATIONAL
        info_res = await client.get("/api/tasks?priority=P3_INFORMATIONAL")
        assert info_res.status_code == 200
        info_tasks = info_res.json()
        assert len(info_tasks) == 1
        assert info_tasks[0]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_get_task_detail_with_logs(temp_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/tasks/1")
        assert res.status_code == 200
        data = res.json()
        assert data["task"]["id"] == 1
        assert data["task"]["title"] == "Pay Semester Tuition"
        assert len(data["logs"]) == 1
        assert data["logs"][0]["tool_name"] == "read_local_file"

        # 404 test
        not_found = await client.get("/api/tasks/9999")
        assert not_found.status_code == 404


@pytest.mark.asyncio
async def test_update_task_status(temp_db):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Mark as completed
        res = await client.patch("/api/tasks/1/status", json={"status": "COMPLETED"})
        assert res.status_code == 200
        assert res.json()["status"] == "COMPLETED"

        # Dismiss task
        res_dismiss = await client.patch("/api/tasks/1/status", json={"status": "DISMISSED"})
        assert res_dismiss.status_code == 200
        assert res_dismiss.json()["status"] == "DISMISSED"

        # Check DB reflects dismissed status
        check_res = await client.get("/api/tasks/1")
        assert check_res.json()["task"]["status"] == "DISMISSED"

        # Restore back to PENDING
        res_restore = await client.patch("/api/tasks/1/status", json={"status": "PENDING"})
        assert res_restore.status_code == 200
        assert res_restore.json()["status"] == "PENDING"


@pytest.mark.asyncio
async def test_run_task_copilot_endpoint(temp_db):
    mock_loop_result = AgentLoopResult(
        task_id=1,
        completed=True,
        final_response="I have drafted a response to the bursar.",
        iterations=2,
        actions_taken=[]
    )

    transport = httpx.ASGITransport(app=app)
    with patch("app.main.ReActAgentHarness.execute_task", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_loop_result

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/tasks/1/run",
                json={"instruction": "Draft a payment confirmation reply."}
            )
            assert res.status_code == 200
            data = res.json()
            assert data["completed"] is True
            assert "drafted a response" in data["final_response"]


@pytest.mark.asyncio
async def test_draft_inspection_and_approval_gate():
    # Pre-stage a draft
    draft_id = "draft_test_1234"
    DraftEmailReplySkill._staged_drafts[draft_id] = {
        "draft_id": draft_id,
        "recipient": "advisor@university.edu",
        "subject": "Re: Appointment",
        "body_markdown": "Confirmed for Monday.",
        "status": "PENDING_APPROVAL"
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Inspect draft
        get_res = await client.get(f"/api/drafts/{draft_id}")
        assert get_res.status_code == 200
        assert get_res.json()["status"] == "PENDING_APPROVAL"

        # 2. Approve draft (HITL Gate)
        with patch("app.tools.smtp_client.SmtpClient.send_email") as mock_send:
            mock_send.return_value = {"success": True}
            approve_res = await client.post(f"/api/drafts/{draft_id}/approve")
            assert approve_res.status_code == 200
            assert approve_res.json()["status"] == "APPROVED"

        # 3. Verify status updated in store
        updated = await client.get(f"/api/drafts/{draft_id}")
        assert updated.json()["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_tasks_ordering_p1_deadlines_and_email_recency(temp_db):
    """
    Verifies that tasks are ordered:
    1. P1_CRITICAL tasks with earliest deadline first.
    2. Non-P1 tasks sorted with most recent email date first.
    """
    with get_db(temp_db) as conn:
        conn.execute("DELETE FROM execution_logs")
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM processed_emails")

        # Insert emails with different dates
        conn.execute(
            """
            INSERT INTO processed_emails (imap_uid, sender, subject, received_at)
            VALUES 
                ('A', 'a@test.com', 'Old email', '2026-10-10 10:00:00'),
                ('B', 'b@test.com', 'New email', '2026-10-20 10:00:00'),
                ('C', 'c@test.com', 'P1 later email', '2026-10-05 10:00:00'),
                ('D', 'd@test.com', 'P1 earlier email', '2026-10-01 10:00:00'),
                ('E', 'e@test.com', 'P1 expired email', '2026-09-01 10:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO tasks (id, email_uid, title, priority_tier, deadline, summary, status)
            VALUES 
                (10, 'A', 'P2 Older Email Task', 'P2_ACTIONABLE', NULL, 'Summary A', 'PENDING'),
                (20, 'B', 'P2 Newer Email Task', 'P2_ACTIONABLE', NULL, 'Summary B', 'PENDING'),
                (30, 'C', 'P1 Later Deadline Task', 'P1_CRITICAL', '2026-10-28 12:00:00', 'Summary C', 'PENDING'),
                (40, 'D', 'P1 Earlier Deadline Task', 'P1_CRITICAL', '2026-10-24 12:00:00', 'Summary D', 'PENDING'),
                (50, 'E', 'P1 Expired Deadline Task', 'P1_CRITICAL', '2026-09-05 12:00:00', 'Summary E', 'PENDING')
            """
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/tasks")
        assert res.status_code == 200
        tasks = res.json()
        
        # Expected order:
        # 1. P1 Earlier Deadline Task (upcoming Oct 24)
        # 2. P1 Later Deadline Task (upcoming Oct 28)
        # 3. P2 Newer Email Task (Oct 20)
        # 4. P2 Older Email Task (Oct 10)
        # 5. P1 Expired Deadline Task (Sept 05 deadline has passed -> sunk to bottom)
        titles = [t["title"] for t in tasks]
        assert titles[0] == "P1 Earlier Deadline Task"
        assert titles[1] == "P1 Later Deadline Task"
        assert titles[2] == "P2 Newer Email Task"
        assert titles[3] == "P2 Older Email Task"
        assert titles[4] == "P1 Expired Deadline Task"


