"""
FastAPI Application Root and REST Routing.
Implements asynchronous endpoints for task management, agent co-pilot execution,
and synchronization.
"""

from contextlib import asynccontextmanager
import logging
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.database import get_db, init_db
from app.harness.agent_loop import AgentLoopResult, ReActAgentHarness
from app.harness.ollama_client import OllamaClient, OllamaClientError
from app.harness.triage_service import TriageService
from app.ingestion.imap_client import ImapSyncClient
from app.schemas import (
    AgentRunRequest,
    ExecutionLogOut,
    HealthResponse,
    PriorityTier,
    StatusUpdateRequest,
    SyncResult,
    TaskDetailOut,
    TaskOut,
    TaskStatus,
)
from app.tools.email_skills import DraftEmailReplySkill

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application Lifespan Event Manager.
    Guarantees database schema is migrated and checks Ollama health on boot.
    """
    logger.info("Initializing SQLite persistence layer...")
    init_db()

    # Diagnostic probe on boot
    try:
        ollama = OllamaClient()
        health = await ollama.check_health()
        logger.info(f"Ollama inference engine status: {health}")
    except Exception as e:
        logger.warning(f"Ollama probe warning: {str(e)}")

    yield
    logger.info("Application shutdown complete.")


app = FastAPI(
    title="Email Agent Backend",
    description="Autonomous local email triage and task assistant API",
    version="0.1.0",
    lifespan=lifespan
)

# CORS Configuration for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
async def get_health():
    """Returns runtime health status for API, SQLite database, and local Ollama daemon."""
    db_status = "unhealthy"
    try:
        with get_db() as conn:
            conn.execute("SELECT 1;").fetchone()
            db_status = "connected (WAL mode)"
    except Exception as e:
        db_status = f"error: {str(e)}"

    ollama_status: Dict[str, Any] = {"online": False}
    try:
        ollama = OllamaClient()
        ollama_status = await ollama.check_health()
    except Exception as e:
        ollama_status = {"online": False, "error": str(e)}

    return HealthResponse(
        status="ok",
        database=db_status,
        ollama=ollama_status
    )


@app.get("/api/tasks", response_model=List[TaskOut])
async def list_tasks(
    status_filter: Optional[TaskStatus] = Query(None, alias="status"),
    priority_filter: Optional[PriorityTier] = Query(None, alias="priority")
):
    """
    Retrieves prioritized tasks queue.
    Supports filtering by status and priority tier.
    Sorted by deadline (nulls last) and insertion order.
    """
    query = """
        SELECT 
            t.id, t.email_uid, t.title, t.deadline, t.priority_tier, 
            t.summary, t.action_url, t.status, t.created_at,
            e.sender, e.subject
        FROM tasks t
        JOIN processed_emails e ON t.email_uid = e.imap_uid
        WHERE 1=1
    """
    params: List[Any] = []

    if status_filter:
        query += " AND t.status = ?"
        params.append(status_filter.value)
    if priority_filter:
        query += " AND t.priority_tier = ?"
        params.append(priority_filter.value)

    query += """
        ORDER BY 
            CASE WHEN t.deadline IS NULL THEN 1 ELSE 0 END, 
            t.deadline ASC, 
            t.id DESC
    """

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [TaskOut.model_validate(dict(row)) for row in rows]


@app.get("/api/tasks/{task_id}", response_model=TaskDetailOut)
async def get_task_detail(task_id: int):
    """Retrieves a single task alongside its full ReAct execution audit log."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                t.id, t.email_uid, t.title, t.deadline, t.priority_tier, 
                t.summary, t.action_url, t.status, t.created_at,
                e.sender, e.subject
            FROM tasks t
            JOIN processed_emails e ON t.email_uid = e.imap_uid
            WHERE t.id = ?
            """,
            (task_id,)
        )
        task_row = cursor.fetchone()
        if not task_row:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        task = TaskOut.model_validate(dict(task_row))

        # Fetch execution logs
        cursor.execute(
            """
            SELECT id, task_id, thought, tool_name, tool_input, tool_output, created_at
            FROM execution_logs
            WHERE task_id = ?
            ORDER BY id ASC
            """,
            (task_id,)
        )
        log_rows = cursor.fetchall()
        logs = [ExecutionLogOut.model_validate(dict(row)) for row in log_rows]

        return TaskDetailOut(task=task, logs=logs)


@app.patch("/api/tasks/{task_id}/status", response_model=TaskOut)
async def update_task_status(task_id: int, request: StatusUpdateRequest):
    """Updates the lifecycle status of a task (e.g. mark COMPLETED or DISMISSED)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (request.status.value, task_id)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Return updated task details
    return (await get_task_detail(task_id)).task


@app.post("/api/tasks/{task_id}/run", response_model=AgentLoopResult)
async def run_task_copilot(task_id: int, request: AgentRunRequest):
    """
    Triggers the multi-turn ReAct Co-Pilot loop to assist with completing a specific task.
    """
    task_detail = await get_task_detail(task_id)
    task = task_detail.task

    harness = ReActAgentHarness()
    try:
        result = await harness.execute_task(
            task_id=task.id,
            task_title=task.title,
            task_summary=task.summary,
            user_instruction=request.instruction
        )
        return result
    except OllamaClientError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Inference Engine Unavailable: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Task co-pilot execution error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Co-Pilot error: {str(e)}"
        )


@app.post("/api/sync", response_model=SyncResult)
async def sync_emails_and_triage():
    """
    Manually triggers an incremental IMAP poll and runs LLM triage on newly fetched emails.
    """
    try:
        imap_client = ImapSyncClient()
        new_emails = imap_client.fetch_unprocessed_emails()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IMAP Sync failed: {str(e)}"
        )

    triage_service = TriageService()
    tasks_created_count = 0

    for email_data in new_emails:
        try:
            result = await triage_service.triage_and_persist(email_data)
            if result.is_actionable:
                tasks_created_count += len(result.tasks)
        except Exception as e:
            logger.error(f"Triage failed for email {email_data.imap_uid}: {str(e)}")

    return SyncResult(
        new_emails=len(new_emails),
        tasks_created=tasks_created_count
    )


@app.get("/api/drafts/{draft_id}")
async def get_staged_draft(draft_id: str):
    """Retrieves a staged email draft for user review before human approval."""
    draft = DraftEmailReplySkill.get_staged_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
    return draft


@app.post("/api/drafts/{draft_id}/approve")
async def approve_staged_draft(draft_id: str):
    """
    Human-in-the-Loop approval gate.
    Marks a staged draft as user-approved.
    """
    draft = DraftEmailReplySkill.get_staged_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")

    draft["status"] = "APPROVED"
    return {
        "draft_id": draft_id,
        "status": "APPROVED",
        "message": "Draft successfully approved for sending."
    }
