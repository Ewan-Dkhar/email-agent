# 📬 Autonomous Local Email Agent

> **A privacy-preserving, local-first email triage assistant and ReAct co-pilot powered by local LLMs.**

Traditional AI email assistants send your personal inbox data to third-party cloud APIs. **Autonomous Local Email Agent** is built from the ground up for **zero cloud data leakage**: all email ingestion, text sanitization, urgency triage, task extraction, and ReAct co-pilot interactions run **100% locally on your machine** using Ollama and an isolated SQLite vault.

---

## ✨ Features

- **🔒 100% Local & Private**: Powered by [Ollama](https://ollama.ai/) (`gemma2:9b` or any compatible local model). Your inbox contents and drafts never leave your device.
- **🛡️ Prompt Injection & Exploit Defense**: Strips tracking pixels, embedded scripts, base64 blobs, hidden styles, and jailbreak directives. Untrusted email contents are strictly enclosed in security boundaries.
- **⚡ Smart Prioritization Queue**:
  - **Upcoming Deadlines First**: `P1_CRITICAL` tasks with looming deadlines are prioritized at the very top.
  - **Email Recency**: Active tasks are chronologically sorted with the latest emails first.
  - **Expired & Done Sinking**: Tasks with passed deadlines and completed/dismissed items automatically sink to the bottom so they never clutter your active inbox.
- **🤖 Interactive ReAct Co-Pilot**:
  - Multi-turn conversational sidebar for each extracted task.
  - Safe tool execution: inspect local reference files in your project workspace (guarded against directory traversal).
  - Human-in-the-loop draft generation: drafts are safely staged for user review and approval.
  - Conversation persistence: sidebar state and drafts are retained across closes via local storage.
- **✅ Task Lifecycle Management**: Filter tasks by status (`PENDING`, `COMPLETED`, `DISMISSED`) and priority tier, with one-click **Mark Done** and **Dismiss** controls.
- **🚀 High-Water Mark IMAP Ingestion**: Fast incremental email fetching ($O(1)$ lookup) using IMAP sequence tracking and idempotency guards.

---

## 🏗️ Architecture

```
                                  ┌──────────────────────────┐
                                  │   Email Server (IMAP)    │
                                  └────────────┬─────────────┘
                                               │ IMAP SSL (Port 993)
                                               ▼
                                  ┌──────────────────────────┐
                                  │  High-Water Mark Sync    │
                                  └────────────┬─────────────┘
                                               ▼
                                  ┌──────────────────────────┐
                                  │ Injection Sanitizer &    │
                                  │ HTML-to-Markdown Parser  │
                                  └────────────┬─────────────┘
                                               │
                                               ▼
 ┌──────────────────────────┐     ┌──────────────────────────┐
 │   Local Ollama Engine    │◄───►│  FastAPI Backend Service │
 │   (e.g. gemma2:9b)       │     │  (Port 8000)             │
 └──────────────────────────┘     └────────────┬─────────────┘
                                               │
                       ┌───────────────────────┴───────────────────────┐
                       ▼                                               ▼
        ┌──────────────────────────┐                    ┌──────────────────────────┐
        │   SQLite Agent Vault     │                    │  React 18 + Vite SPA     │
        │   (agent_vault.db)       │                    │  (Port 5173)             │
        └──────────────────────────┘                    └──────────────────────────┘
```

---

## 📋 Prerequisites

Before installing, make sure your computer has the following tools installed:

1. **Python 3.12+** (or Python 3.11+)
   - Check with: `python3 --version`
2. **Node.js 18+ & npm**
   - Check with: `node --version && npm --version`
3. **[Ollama](https://ollama.ai/)** (Local LLM runner)
   - Install Ollama for Linux, macOS, or Windows from [ollama.ai](https://ollama.ai/).
4. **An IMAP-enabled Email Account** (e.g. Gmail, Outlook, Fastmail, or custom mail server).

---

## 🔑 IMAP & App Password Setup Guide

For security, modern email providers (like Google) require an **App Password** rather than your regular account password when authenticating third-party IMAP clients.

### Setting Up Gmail (Recommended)

Follow these steps to obtain a Gmail App Password:

#### Step 1: Enable 2-Step Verification
1. Navigate to your [Google Account Security Settings](https://myaccount.google.com/security).
2. Under **"How you sign in to Google"**, select **2-Step Verification** and follow the prompts to enable it (if not already enabled).

#### Step 2: Generate an App Password
1. In Google Account Security, search for **"App passwords"** in the top search bar (or go to [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)).
2. Under **App name**, enter a descriptive name (e.g., `Email Agent`).
3. Click **Create**.
4. Google will generate a **16-character passcode** (e.g., `abcd efgh ijkl mnop`).
5. **Copy this 16-character code** (spaces can be omitted or kept). You will paste this into `config.yaml`.

#### Step 3: Ensure IMAP is Enabled in Gmail
1. Open [Gmail](https://mail.google.com/) in your browser.
2. Click the gear icon (**Settings**) in the top right -> **See all settings**.
3. Click the **Forwarding and POP/IMAP** tab.
4. Under the **IMAP access** section, select **Enable IMAP**.
5. Click **Save Changes** at the bottom of the page.

> [!NOTE]
> **For Other Email Providers:**
> - **Outlook / Hotmail**: Server: `outlook.office365.com`, Port: `993`, SSL: `true`. Generate an App Password under Microsoft Account Security.
> - **Yahoo Mail**: Server: `imap.mail.yahoo.com`, Port: `993`, SSL: `true`. Generate an App Password under Account Security.
> - **Fastmail / Custom IMAP**: Use your provider's IMAP SSL hostname and port `993` with an app-specific token.

---

## ⚙️ Local Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Ewan-Dkhar/email-agent.git
cd email-agent
```

### 2. Set Up Local LLM (Ollama)

1. Start the Ollama background daemon (if not already running):
   ```bash
   ollama serve
   ```
2. Pull the recommended triage and reasoning model:
   ```bash
   ollama pull gemma2:9b
   ```
   *(Note: You can also use other models such as `mistral`, `llama3.1:8b`, or `qwen2.5:7b` by updating `config.yaml`.)*

---

### 3. Configure the Backend

1. Create your local `config.yaml` from the provided template:
   ```bash
   cp config.example.yaml config.yaml
   ```
2. Edit `config.yaml` with your email and App Password:
   ```yaml
   server:
     host: "127.0.0.1"
     port: 8000

   database:
     path: "agent_vault.db"

   ollama:
     base_url: "http://127.0.0.1:11434"
     model: "gemma2:9b"
     timeout_seconds: 120.0

   imap:
     host: "imap.gmail.com"
     port: 993
     use_ssl: true
     username: "your_email@gmail.com"
     password: "your_16_character_app_password"
     mailbox: "INBOX"
     poll_interval_seconds: 900
   ```

> [!WARNING]
> `config.yaml` contains sensitive credentials and is strictly excluded by `.gitignore`. Never commit `config.yaml` to source control.

---

### 4. Install Backend Dependencies & Run Server

1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. Start the FastAPI development server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   The backend API will be running at `http://127.0.0.1:8000`. You can view the OpenAPI interactive documentation at `http://127.0.0.1:8000/docs`.

---

### 5. Install Frontend Dependencies & Run Web App

1. In a new terminal window, navigate to the `frontend/` directory:
   ```bash
   cd frontend
   ```
2. Install npm packages:
   ```bash
   npm install
   ```
3. Start the Vite dev server:
   ```bash
   npm run dev
   ```
4. Open your browser and navigate to:
   ```
   http://localhost:5173/
   ```

---

## 🖥️ Using the Application

### 1. Syncing Emails
- Click the **"Sync Mailbox Now"** button in the top navigation bar.
- The backend connects via IMAP SSL, pulls unprocessed emails using the incremental high-water mark cursor, strips dangerous payloads, and triggers Ollama triage.
- Extracted actionable tasks automatically populate the queue.

### 2. Navigating the Task Queue
- **Active Priorities**: Tasks with active upcoming deadlines (e.g. within 48h) sit at the top.
- **Recent Emails**: Active tasks are sorted chronologically with the latest received emails first.
- **Passed Deadlines & Completed Items**: Automatically sink to the bottom in muted styling so your active queue stays uncluttered.
- **Filtering**: Use the filter pills at the top to filter by status (`ALL`, `PENDING`, `COMPLETED`, `DISMISSED`) or priority tier (`P1_CRITICAL`, `P2_ACTIONABLE`, `P3_INFORMATIONAL`).

### 3. Task Actions
- **Mark Done**: Toggles task status between `PENDING` and `COMPLETED`.
- **Dismiss**: Dismisses unnecessary tasks, moving them out of the active pending view. Dismissed tasks can be viewed and restored at any time under the `DISMISSED` filter.
- **Open Link**: If an email contains a direct action portal or form link, click to open it directly.

### 4. Working with the Co-Pilot Sidebar
- Click **"Work with Co-Pilot"** on any task card to slide open the interactive ReAct drawer.
- **Ask questions**: Ask the agent to summarize context, verify details, or explain next steps.
- **Inspect local files**: The agent can inspect reference documents or notes in your workspace via the `read_local_file` skill.
- **Draft an email reply**: Ask the agent to *"Draft a polite reply confirming attendance"* or *"Draft an email requesting an extension"*.
- **Review & Approve Drafts**: Staged email drafts are displayed in a clean preview card. Click **"Approve Draft"** to stage and approve the response.
- **Session Persistence**: Close the sidebar anytime by clicking outside or pressing <kbd>Esc</kbd>—your conversation turns and draft previews are automatically preserved when you reopen the task.

---

## 🧪 Running Automated Tests

The repository includes a comprehensive automated test suite covering database constraints, prompt injection sanitization, IMAP deduplication, ReAct loop circuit breakers, and REST API endpoints.

To run the backend test suite:

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

To validate the frontend TypeScript build:

```bash
cd frontend
npm run build
```

---

## 📁 Repository Structure

```
email-agent/
├── backend/
│   ├── app/
│   │   ├── config.py              # YAML configuration loader & validation
│   │   ├── database.py            # SQLite schema, PRAGMAs, and connection pools
│   │   ├── schemas.py             # Strict Pydantic v2 domain schemas & enums
│   │   ├── main.py                # FastAPI endpoints & query ordering logic
│   │   ├── harness/
│   │   │   ├── agent_loop.py      # ReAct multi-turn co-pilot loop with circuit breakers
│   │   │   ├── ollama_client.py   # Async local Ollama client with JSON validation
│   │   │   ├── prompt_builder.py  # Temporal grounding & boundary tag isolation
│   │   │   └── triage_service.py  # Email triage orchestration & database persistence
│   │   ├── ingestion/
│   │   │   ├── imap_client.py     # Secure SSL IMAP incremental fetching client
│   │   │   └── sanitizer.py       # Prompt injection scrubbing & date normalizer
│   │   └── tools/
│   │       ├── registry.py        # Co-pilot skill registry & dispatcher
│   │       ├── email_skills.py    # Staged draft creation with HITL gate
│   │       └── file_skills.py     # Path-traversal guarded workspace file reader
│   ├── tests/                     # 29 automated pytest unit & integration tests
│   └── pyproject.toml             # Python package dependencies & metadata
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── AgentDrawer.tsx    # ReAct co-pilot sidebar with persistent storage
│   │   │   ├── TaskCard.tsx       # Task queue card with dismiss/done controls
│   │   │   └── PriorityBadge.tsx  # Color-coded urgency badge
│   │   ├── types.ts               # Shared TypeScript domain contracts
│   │   ├── api.ts                 # REST client for backend endpoints
│   │   └── App.tsx                # Main dashboard layout, sync & status filters
│   ├── package.json
│   └── vite.config.ts
├── config.example.yaml            # Safe configuration template
└── README.md
```

---

## 🛡️ Privacy & Security Commitments

1. **Zero External Telemetry**: No user data, subject lines, or body text are transmitted over the internet.
2. **Local Inference Only**: Ollama communicates strictly through loopback HTTP (`127.0.0.1:11434`).
3. **Defense Against Prompt Injections**: Incoming emails are treated as untrusted data inputs. Instructions embedded within email text cannot hijack agent directives or system prompts.
4. **Human-in-the-Loop Safeguards**: Actions that create outgoing drafts require explicit human review and approval.

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
