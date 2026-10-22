"""
Data Transfer Objects and Domain Models.
Strict Pydantic v2 schemas for parsing, storage, and API transmission.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class PriorityTier(str, Enum):
    P1_CRITICAL = "P1_CRITICAL"       # Hard deadline <= 48h, fees, legal/academic jeopardy
    P2_ACTIONABLE = "P2_ACTIONABLE"   # Requires follow-up/reply, deadline > 48h or indefinite
    P3_INFORMATIONAL = "P3_INFORMATIONAL" # Read-only, newsletters, general broadcast notices


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISMISSED = "DISMISSED"


class ExtractedTask(BaseModel):
    title: str = Field(description="Action verb + object, e.g. 'Submit Elective Choice Form'")
    priority: PriorityTier = Field(description="Calculated urgency tier")
    deadline: Optional[str] = Field(None, description="Calculated ISO 8601 timestamp (YYYY-MM-DD HH:MM) or null")
    summary: str = Field(description="1-2 sentences on what must be done and why")
    action_url: Optional[str] = Field(None, description="Direct URL to portal, form, or document if found")


class EmailTriageResult(BaseModel):
    is_actionable: bool = Field(description="True if this email requires user action or response")
    tasks: List[ExtractedTask] = Field(default_factory=list, description="Extracted actionable tasks")



class SanitizedEmail(BaseModel):
    imap_uid: str
    sender: str
    subject: str
    received_at: str
    cleaned_body: str
    raw_snippet: str


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_uid: str
    title: str
    deadline: Optional[str]
    priority_tier: PriorityTier
    summary: str
    action_url: Optional[str]
    status: TaskStatus
    sender: str
    subject: str
    created_at: str
    received_at: Optional[str] = None


class StatusUpdateRequest(BaseModel):
    status: TaskStatus = Field(description="Target lifecycle state for the task")


class ExecutionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    thought: Optional[str] = None
    tool_name: str
    tool_input: str
    tool_output: str
    created_at: str


class TaskDetailOut(BaseModel):
    task: TaskOut
    logs: List[ExecutionLogOut] = Field(default_factory=list)


class AgentRunRequest(BaseModel):
    instruction: str = Field(description="User prompt or instruction for the co-pilot")


class SyncResult(BaseModel):
    new_emails: int
    tasks_created: int


class HealthResponse(BaseModel):
    status: str
    database: str
    ollama: dict


class ToolCallAction(BaseModel):
    name: str = Field(description="Name of the tool to invoke")
    arguments: dict = Field(default_factory=dict, description="Arguments dictionary for the tool")


class CoPilotResponse(BaseModel):
    thought: str = Field(description="Step-by-step reasoning about the task and current state")
    action: Optional[ToolCallAction] = Field(None, description="Tool action to run, or null if providing final answer")
    final_answer: Optional[str] = Field(None, description="Final user-facing response when task is completed or no tool is needed")



