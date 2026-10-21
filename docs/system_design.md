# SYSTEM_DESIGN.md - Component Specifications & Data Contracts

## 1. Complete Tech Stack Justifications

| Component | Technology | Architectural Rationale |
| :--- | :--- | :--- |
| **Language** | Python 3.12+ | High-performance Pydantic v2 validation via Rust core, native `asyncio`, rich IMAP/MIME parsing ecosystem. |
| **Inference Engine**| Ollama (`llama.cpp` core) | GGUF Q4_K_M quantization fits Gemma-2-9B in ~5.5GB VRAM. Automatically unloads from VRAM when idle (`keep_alive`), freeing memory for other host applications. |
| **Model** | Gemma-2-9B-IT | High reasoning density, strong instruction-following, reliable JSON schema compliance. |
| **Database** | SQLite3 (WAL Mode) | Embedded, zero-configuration, single-file storage. WAL mode decouples reader processes from writer processes with zero network IPC overhead. |
| **Validation** | Pydantic v2 | Strict data contracts, instant OpenAPI generation, compile-time type safety. |
| **Web Server** | FastAPI + Uvicorn | Asynchronous request handling, native Pydantic integration, clean REST JSON interfaces. |
| **Frontend** | React + TypeScript + Vite | Decoupled client-side SPA. Strict TypeScript types prevent runtime interface crashes. Pure JSON consumption keeps server and UI completely decoupled. |

---

## 2. Database Design & Relational Schema

The database engine is SQLite3 running with `PRAGMA journal_mode = WAL` and `PRAGMA foreign_keys = ON`.

```
                    ┌─────────────────────────┐
                    │     processed_emails    │
                    ├─────────────────────────┤
                    │ PK  id                  │
                    │ UQ  imap_uid            │
                    │     sender              │
                    │     subject             │
                    │     received_at         │
                    │     raw_snippet         │
                    │     processed_at        │
                    └───────────┬─────────────┘
                                │ 1
                                │
                                │ N
                    ┌───────────▼─────────────┐
                    │          tasks          │
                    ├─────────────────────────┤
                    │ PK  id                  │
                    │ FK  email_uid           │
                    │     title               │
                    │     deadline            │
                    │     priority_tier       │
                    │     summary             │
                    │     action_url          │
                    │     status              │
                    │     created_at          │
                    └───────────┬─────────────┘
                                │ 1
                                │
                                │ N
                    ┌───────────▼─────────────┐
                    │      execution_logs     │
                    ├─────────────────────────┤
                    │ PK  id                  │
                    │ FK  task_id             │
                    │     thought             │
                    │     tool_name           │
                    │     tool_input          │
                    │     tool_output         │
                    │     created_at          │
                    └─────────────────────────┘
```

### 2.1 DDL Schema
```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS processed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imap_uid TEXT UNIQUE NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    raw_snippet TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_uid TEXT NOT NULL,
    title TEXT NOT NULL,
    deadline TEXT, -- ISO 8601 (YYYY-MM-DD HH:MM) or NULL
    priority_tier TEXT NOT NULL CHECK(priority_tier IN ('P1_CRITICAL', 'P2_ACTIONABLE', 'P3_INFORMATIONAL')),
    summary TEXT NOT NULL,
    action_url TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'DISMISSED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (email_uid) REFERENCES processed_emails(imap_uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    thought TEXT,
    tool_name TEXT NOT NULL,
    tool_input TEXT NOT NULL, -- JSON string
    tool_output TEXT NOT NULL, -- JSON string
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_priority_status ON tasks(priority_tier, status);
CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks(deadline);
CREATE INDEX IF NOT EXISTS idx_emails_uid ON processed_emails(imap_uid);
```

---

## 3. Data Transfer Objects (Pydantic Schemas)

```python
# backend/app/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum

class PriorityTier(str, Enum):
    P1_CRITICAL = "P1_CRITICAL"       # Hard deadline <= 48h, exam forms, fees, legal/academic jeopardy
    P2_ACTIONABLE = "P2_ACTIONABLE"   # Requires follow-up/reply, deadline > 48h or indefinite
    P3_INFORMATIONAL = "P3_INFORMATIONAL" # Read-only, newsletters, general broadcast notices

class ExtractedTask(BaseModel):
    title: str = Field(..., description="Action verb + object, e.g. 'Submit Elective Choice Form'")
    priority: PriorityTier = Field(..., description="Calculated urgency tier")
    deadline: Optional[str] = Field(None, description="Calculated ISO 8601 timestamp (YYYY-MM-DD HH:MM) or null")
    summary: str = Field(..., description="1-2 sentences on what must be done and why")
    action_url: Optional[str] = Field(None, description="Direct URL to portal, form, or document if found")

class EmailTriageResult(BaseModel):
    is_actionable: bool = Field(..., description="True if this email requires user action or response")
    tasks: List[ExtractedTask] = Field(default_factory=list, description="Extracted actionable tasks")

class TaskOut(BaseModel):
    id: int
    title: str
    deadline: Optional[str]
    priority_tier: PriorityTier
    summary: str
    action_url: Optional[str]
    status: str
    sender: str
    subject: str

class StatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(PENDING|IN_PROGRESS|COMPLETED|DISMISSED)$")
```

---

## 4. The Harness ReAct State Machine

The Agent Harness coordinates communication between the model and the operating environment.

```
       [Start Task Execution]
                 │
                 ▼
     [Construct Prompt Buffer]
  System Context + Tools + History
                 │
                 ▼
       ┌──────────────────┐
       │   Call Gemma     │◄─────────────────────────────┐
       └─────────┬────────┘                              │
                 │                                       │
     Has Tool Call in output?                            │
                 │                                       │
         ┌───────┴───────┐                               │
         ▼               ▼                               │
       [Yes]            [No]                             │
         │               │                               │
  Validate Args          └─► [Final Answer Reached]      │
         │                         │                     │
    ┌────┴────┐                    ▼                     │
    ▼         ▼             Mark Task Resolved           │
 [Valid]  [Invalid]                │                     │
    │         │                    ▼                     │
 Execute   Emit Error          [Finish]                  │
  Skill     Message                                      │
    │         │                                          │
    └────┬────┘                                          │
         │                                               │
  Append Result as Tool Observation ─────────────────────┘
```

### 4.1 Temporal Grounding Protocol
LLMs cannot perceive physical time. Every inference call to Gemma must construct a system context that explicitly declares the temporal reference:
- Current ISO Datetime: `YYYY-MM-DD HH:MM:SS`
- Current Day of the Week: e.g., `Monday`
- Calculation Anchor: `"Friday at 5 PM"` must mathematically map to the upcoming Friday relative to this timestamp.

---

## 5. Network & Connection Specifications

- **Ollama API:** `http://127.0.0.1:11434/api/chat`
  - Zero temperature (`temperature: 0.0`) for triage extraction.
  - Low temperature (`temperature: 0.2`) for task co-pilot execution.
- **FastAPI Server:** `http://127.0.0.1:8000`
- **Vite Development Server:** `http://127.0.0.1:5173`
  - Proxies `/api/*` to `127.0.0.1:8000`.