# ARCHITECTURAL_DESIGN.md - Autonomous Email Triage & Action Harness

## 1. High-Level System Architecture

This software system is an autonomous, privacy-preserving desktop application that continuously ingests raw emails, extracts actionable obligations and firm deadlines, categorizes them into an immediate/urgent task queue, and assists the user in completing the work through an interactive co-pilot loop.

The architecture strictly decouples **Background Triage & Perception** from **Interactive Task Co-Pilot & Actuation**.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL WORLD / ENVIRONMENT                    │
│               IMAP Mail Server (Gmail / College / Exchange)            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Unseen MIME payload
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   INGESTION & CLEANING PIPELINE                        │
│  - IMAP Poller (Python standard library imaplib)                       │
│  - MIME Parser & Sanitizer (BeautifulSoup4 + Markdownify)              │
│  - Temporal Grounder (Injects current system timestamp & day-of-week)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Sanitized text + Temporal prompt
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   TRIAGE ENGINE (Ollama / Gemma-2-9B)                  │
│  - Grammar-constrained decoding via Pydantic v2 JSON Schema            │
│  - Outputs structured EmailTriageResult (Urgency, Deadline, Actions)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Strict JSON
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               LOCAL PERSISTENCE LAYER (SQLite3 in WAL Mode)            │
│  - processed_emails (Deduplication via imap_uid)                       │
│  - tasks (Prioritized queue: P1_CRITICAL, P2_ACTIONABLE, P3_INFO)      │
│  - execution_logs (Audit trail of agent actions)                       │
└───────────────▲───────────────────────────────────────┬────────────────┘
                │ Reads / Updates State                 │ Reads Queue
                │                                       ▼
┌───────────────┴────────────────────────────────────────────────────────┐
│                   FASTAPI ASYNCHRONOUS BACKEND                         │
│  - REST Endpoints (/api/tasks, /api/tasks/{id}/status)                 │
│  - Tool Dispatcher & Agent Harness (ReAct Loop)                        │
└───────────────────────────────────▲────────────────────────────────────┘
                                    │ Pure JSON over HTTP / REST
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│              FRONTEND WORKSPACE (React + TypeScript + Vite)            │
│  - Reactive Dashboard (Tailwind CSS)                                   │
│  - Task Queue & Deadline Tracking                                      │
│  - Interactive Agent Drawer (ReAct loop progress & human confirmation) │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architectural Features

### 2.1 Two-Phase Execution Separation
1. **Background Triage Worker (Perception Layer):**
   - Runs on a periodic schedule (e.g., every 15–30 minutes) or via IMAP IDLE.
   - Operates in a stateless, one-shot extraction mode.
   - Extracts deadlines, links, and priorities into SQLite without human intervention.
2. **Interactive Task Co-Pilot (Actuation Layer):**
   - Runs on-demand when the user activates the web UI.
   - Operates as a stateful ReAct (Reason + Act) loop.
   - Has access to active tools (file search, reply drafting, web scraping) to help complete specific tasks.

### 2.2 Strict Grammar-Constrained Decoding
Open-weight models can produce invalid JSON or arbitrary date formats under temperature fluctuations. The architecture eliminates this by feeding Pydantic JSON schemas directly into Ollama's `format` parameter. The model's sampling logits are masked at the token level, guaranteeing valid, parseable JSON on every inference pass.

### 2.3 Strict Human-in-the-Loop (HITL) Gate
Read actions (reading local files, parsing emails, summarizing links) are autonomous. Write actions (sending an email reply, submitting an external form, deleting records) are strictly staged in SQLite as `DRAFT` or `PENDING_APPROVAL`. Actuation requires explicit user confirmation via the frontend.

### 2.4 Cross-Platform Hardware Abstraction
The system avoids OS-specific paths and hardware-specific compilation flags:
- All paths are derived using Python's `pathlib.Path` relative to the user's home directory.
- Model execution relies on standard Ollama HTTP endpoints (`http://127.0.0.1:11434`), supporting layer offloading across diverse GPU/CPU profiles (Nvidia, AMD, Apple Silicon, CPU fallback).

---

## 3. Project Directory Structure

```
email-agent/
├── docs/                           # Guides on architectural & system design, skill architecture and agent guidelines
│   ├── agent_guidelines.md
│   ├── architectural_design.md
│   ├── skills_architecture.md
│   └── system_design.md
├── config.yaml                     # Local server & mailbox settings
├── backend/
│   ├── pyproject.toml              # UV / Pip dependency manifest
│   ├── agent_vault.db              # SQLite Database (auto-generated)
│   └── app/
│       ├── __init__.py
│       ├── main.py                 # FastAPI application root & CORS
│       ├── config.py               # Pydantic Settings
│       ├── database.py             # SQLite WAL connection manager
│       ├── schemas.py              # Shared Pydantic data models
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── imap_client.py      # Mailbox poller & UID synchronizer
│       │   └── sanitizer.py        # MIME stripper & text normalizer
│       ├── harness/
│       │   ├── __init__.py
│       │   ├── agent_loop.py       # ReAct state machine
│       │   ├── ollama_client.py    # Local inference connector
│       │   └── prompt_builder.py   # Temporal anchor & system prompts
│       └── tools/
│           ├── __init__.py
│           ├── base.py             # BaseSkill abstract class
│           ├── registry.py         # Dynamic skill loader
│           ├── email_skills.py     # Draft email, parse thread
│           └── filesystem_skills.py# Read attachments, search docs
└── frontend/
    ├── package.json
    ├── vite.config.ts              # Proxying /api to 127.0.0.1:8000
    ├── tsconfig.json
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx                 # Root layout & active queue
        ├── types.ts                # TypeScript types mirroring Pydantic
        ├── api.ts                  # Type-safe Fetch API client
        └── components/
            ├── TaskCard.tsx        # Individual task component
            ├── PriorityBadge.tsx   # Visual indicator (P1/P2/P3)
            └── AgentDrawer.tsx     # Interactive ReAct execution modal
```

---

## 4. How AI Agents Should Use This File
1. **Scope Verification:** Any code written must belong to one of the defined directory boundaries above. Do not introduce monolithic single-file scripts.
2. **Zero Cloud Bleed:** Do not introduce external LLM cloud dependencies (OpenAI, Anthropic, Gemini API). All inference logic must target local endpoints via `backend/app/harness/ollama_client.py`.
3. **Schema Preservation:** Any modification to backend data representations must be reflected in `backend/app/schemas.py` and immediately mirrored in `frontend/src/types.ts`.