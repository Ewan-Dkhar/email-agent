# AGENTS.md - Context & Coding Instructions for AI Assistants

## 1. Project Purpose & Core Problem
The user previously almost missed a critical academic/administrative deadline because important notices were buried under high volumes of everyday emails.

This project solves that exact problem. It is an **autonomous, private, local triage engine and task assistant**.
- It runs locally on the host machine in a self-contained, privacy-preserving environment.
- It uses open-weight **Gemma-2-9B** (or an equivalent local model) served via **Ollama**.
- It reads emails via **IMAP**, sanitizes text, extracts deadlines, and populates a high-priority **SQLite** task queue.
- It provides a **React + TypeScript** web dashboard backed by **FastAPI** to help the user complete tasks efficiently.

---

## 2. Hardware Profile & System Constraints

The software is engineered to be **cross-platform and machine-independent** (Linux, macOS, Windows).

### Hardware Baselines
- **Inference Requirements:** An accelerator with at least **8 GB VRAM** (or unified memory on Apple Silicon) is recommended to comfortably load 4-bit quantized Gemma-2-9B (Q4_K_M $\approx 5.5\text{ GB}$) alongside context and KV caches. 
- **Graceful Degradation:** The engine leverages Ollama/llama.cpp's dynamic layer offloading. On lower-VRAM configurations or CPU-only setups, execution will split layers across system RAM automatically without crashing, albeit with reduced tokens-per-second throughput.
- **Portability Rule:** All file operations, directory paths, and runtime subprocesses must use standard library abstractions (`pathlib.Path`, cross-platform environment variables). Never hardcode OS-specific paths (e.g., `/home/...` or `C:\...`).

---

## 3. Hard Invariants (DO NOT BREAK)

### 3.1 Zero Cloud Exposure
Never write code that imports or calls external commercial LLM APIs (OpenAI, Anthropic, Google Cloud API). All LLM calls must go through the local Ollama instance (`http://127.0.0.1:11434` or configured host). User emails contain private correspondence and records that must remain strictly local.

### 3.2 Strict Structured Outputs
Never ask the local model to output free-form text when extracting tasks. You must pass a strict Pydantic JSON schema to Ollama's `format` option. If you modify the task schema, you must update:
1. `backend/app/schemas.py`
2. `frontend/src/types.ts`
3. SQLite table definitions in `backend/app/database.py`

### 3.3 Always Anchor Temporal Context
LLMs have no internal clock. Every triage and copilot prompt must inject:
- The exact current date and time (ISO format)
- The current day of the week
All relative expressions ("by tomorrow at 5", "next Monday") must be resolved by the model relative to this temporal anchor.

### 3.4 Human-in-the-Loop for Write Operations
The agent must never send an email, submit an external HTTP form, or delete a task autonomously. It can only:
- Create drafts
- Extract links
- Fill out preview states
The final actuation step requires a human button click in the web UI.

---

## 4. Developer Workflow & Run Commands

### 4.1 Backend Setup
```bash
cd backend
# Using standard virtualenv
python -m venv .venv

# Activate environment:
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate

pip install fastapi uvicorn pydantic beautifulsoup4 markdownify httpx
# Run FastAPI server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 4.2 Frontend Setup
```bash
cd frontend
npm install
npm run dev
# Running on http://localhost:5173
```

### 4.3 Ollama Runtime Verification
Ensure the Ollama service is active and the model is downloaded:
```bash
ollama list
# Verify gemma2:9b is present. If not:
ollama pull gemma2:9b
```

---

## 5. How to Make Changes

### Adding a New API Endpoint
1. Define the input/output schemas in `backend/app/schemas.py`.
2. Add the route handler in `backend/app/main.py`.
3. Use the `get_db()` context manager from `backend/app/database.py` for database operations.
4. Update `frontend/src/api.ts` with a type-safe fetch function.
5. Update `frontend/src/types.ts` to match the schema changes.

### Adding a New Skill to the Agent
1. Follow the guidelines in `Skills.md`.
2. Implement the skill in `backend/app/tools/`.
3. Register the skill with the singleton `registry`.
4. The ReAct harness will automatically include it in the next inference cycle.

### Modifying the Database
1. Update table creation statements in `backend/app/database.py`.
2. If changing table columns on an existing database, write an `ALTER TABLE` statement or delete `backend/agent_vault.db` during development to allow it to regenerate cleanly.