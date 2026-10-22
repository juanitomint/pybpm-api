# AGENTS.md — PyBPM (pybpm/)

## Project Overview

A high-performance **FastAPI** backend for the BPM suite. It utilizes **SQLAlchemy (Async)** for database operations, **Alembic** for schema migrations, and **Pydantic v2** for data validation and settings. The architecture follows a service-based pattern to keep API routes thin and business logic decoupled.

## Tech Stack

- **Framework**: FastAPI (Asynchronous API)
- **Data Validation**: Pydantic v2 (Schemas & Settings)
- **ORM**: SQLAlchemy 2.0 (Asynchronous)
- **Migrations**: Alembic
- **Database**: PostgreSQL (via `asyncpg`)
- **Package Manager**: `uv`

## Architecture

```
pybpm-api/
├── main.py                 # FastAPI app, middleware, router wiring
├── config.py               # Pydantic-settings-style Config class
├── extensions.py           # Async engine/session factories, DB deps
├── conftest.py             # Root-level pytest fixtures
├── pyproject.toml          # Dependencies + tool config
├── ruff.toml               # Ruff linting/formatting config
├── Dockerfile              # Multi-stage: python:3.14-slim + uv
├── docker-compose.yml      # App + PostgreSQL service
├── boot.sh                 # Startup: db migration → uvicorn
├── init.sql                # Initial DB schema
├── app/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── admin.py        # GET /admin/health
│   │   ├── auth.py         # POST /api/v1/auth/token, GET /api/v1/auth/me
│   │   ├── bpm/
│   │   │   ├── __init__.py
│   │   │   ├── repository.py  # Model CRUD (prefix: /bpm/repository)
│   │   │   ├── engine.py    # Case lifecycle: newcase, start, run, post, assign
│   │   │   ├── cases.py     # Case manager endpoints (prefix: /bpm/case_manager)
│   │   │   ├── cases_rest.py  # Case manager REST endpoints
│   │   │   ├── tokens.py    # Token manager endpoints (prefix: /bpm/token_manager)
│   │   │   ├── token_manager.py  # Token manager REST endpoints
│   │   │   └── event_schedule.py  # Scheduled events (prefix: /events/schedules)
│   │   ├── dashboard.py    # Case/task counts, task lifecycle (lock/unlock/validate/done)
│   │   ├── inbox.py        # Inbox message filtering, CRUD
│   │   ├── groups.py       # Group CRUD (prefix: /groups)
│   │   ├── users.py        # User CRUD (prefix: /users)
│   │   ├── profile.py      # User profile (prefix: /users, mounted with users_router)
│   │   └── rbac.py         # RBAC management (prefix: /rbac)
│   ├── core/
│   │   ├── logging.py      # Uvicorn log config builder
│   │   └── scheduler.py    # APScheduler start/stop
│   ├── handlers/
│   │   ├── __init__.py     # Auto-registration of all handlers
│   │   ├── flow.py         # SequenceFlow, MessageFlow, _safe_eval
│   │   ├── gate.py         # ParallelGateway, ExclusiveDatabasedGateway, EventbasedGateway
│   │   ├── task.py         # User/Manual/Script/Send/Receive task types
│   │   ├── event.py        # Intermediate events (timer, message, signal, error, etc.)
│   │   ├── start_end.py    # StartNone/Message/Timer, EndNone/Message/Error/Cancel/Terminate
│   │   ├── subproc.py      # CollapsedSubprocess (child case delegation)
│   │   └── eval_context.py # Script execution namespace builder
│   ├── models/
│   │   ├── base.py         # SQLAlchemy DeclarativeBase
│   │   ├── bpm_model.py    # BpmModel — BPMN model JSON + SVG storage
│   │   ├── case.py         # BpmCase — case instance (parent/child hierarchy)
│   │   ├── token.py        # Token, TokenHistory — workflow execution tokens
│   │   ├── user.py         # User
│   │   ├── group.py        # Group
│   │   ├── user_group.py   # UserGroup
│   │   ├── permission_group.py
│   │   ├── permission_repository.py
│   │   ├── message.py      # Message — inbox items
│   │   ├── signal.py       # Signal definitions
│   │   ├── event_schedule.py # Scheduled event triggers
│   │   └── __init__.py
│   ├── schemas/
│   │   ├── case.py
│   │   ├── dashboard.py
│   │   ├── engine.py
│   │   ├── event_schedule.py
│   │   ├── inbox.py
│   │   ├── repository.py
│   │   ├── token.py
│   │   ├── user.py
│   │   └── __init__.py
│   └── services/
│       ├── engine_service.py  # Core engine: token lifecycle, shape dispatch, movenext
│       ├── bpm_service.py     # gen_case, startcase, subprocess orchestration
│       ├── scheduler_service.py # Due schedule dispatch
│       ├── inbox_service.py   # Inbox message operations
│       ├── model_service.py   # Model CRUD operations
│       ├── event_schedule_service.py
│       ├── signal_service.py
│       ├── user_service.py
│       ├── group_service.py
│       ├── rbac_service.py
│       └── profile_service.py
├── migrations/              # Alembic migration files
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 2026_08_26_0000-initial_schema.py
│       └── 2026_09_30_1542-2e39fec2af79_add_signal_resource_id.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_engine_service.py
│   ├── test_flow_handlers.py
│   ├── test_gate_handlers.py
│   ├── test_task_handlers.py
│   ├── test_eval_context.py
│   ├── test_cancel_logic.py
│   ├── test_dashboard_lock_unlock.py
│   ├── test_dashboard_tasks.py
│   ├── test_inbox_api.py
│   ├── test_movenext_outgoing.py
│   ├── test_event_schedule_api.py
│   ├── test_post_engine.py
│   ├── test_run_engine.py
│   ├── test_rbac_paths.py
│   └── test_signal_service.py
├── tools/
│   ├── seed_models.py
│   ├── seed_tasktype.py
│   ├── seed_users.py
│   ├── seed_groups.py
│   ├── seed_inbox.py
│   ├── test_model_parallel.py
│   ├── test_save_raw.py
│   └── asyncio / sys         # Utility scripts
└── files/
    └── images/
        ├── model/           # BPMN model JSON files
        ├── svg/             # SVG renderings of models
        ├── png/             # PNG thumbnails
        ├── zip/             # BPMN model archives (test cases)
        └── raw/             # Raw test data
```

Note: The BPM Engine, RBAC service, Scheduler, Case Manager, Inbox, and Dashboard components have been ported from the legacy `dna2bpm/application/modules/bpm/` codebase. Remaining work: additional handler coverage for edge-case BPMN constructs, and any remaining legacy controllers not yet mapped to FastAPI endpoints.

## Development Workflow

### 1. Data Modeling & Validation
To add a new entity, follow this sequence:
1. **Define Model**: Create a SQLAlchemy class in `app/models/`.
2. **Define Schemas**: Create Pydantic models in `app/schemas/` for:
   - `Create[Entity]`: For POST/PUT requests (no ID, extra fields).
   - `[Entity]Read`: For GET responses (includes ID, timestamps).
   - `[Entity]Update`: For PATCH requests (all fields optional).
3. **Generate Migration**:
   ```bash
   uv run alembic revision --autogenerate -m "Add [Entity Name]"
   ```
4. **Apply Migration**:
   ```bash
   uv run alembic upgrade head
   ```

### 2. Implementing Business Logic (Service Layer)
Keep routers thin. The flow should be:
`Router (FastAPI) -> Service (Logic) -> Model (SQLAlchemy) -> DB`

- **Service**: Contains all complex logic, calculations, and calls to other services. It accepts/returns Pydantic schemas or SQLAlchemy models.
- **Router**: Handles HTTP concerns (status codes, dependencies, parsing path/query params) and calls the appropriate service.

### 3. API Development (FastAPI)
Use type hints for automatic OpenAPI documentation:
```python
@router.post("/", response_model=CaseRead, status_code=201)
async def create_case(
    case_in: CaseCreate, service: CaseService = Depends(get_case_service)
):
    return await service.create(case_in)
```

### 4. Testing
Use `pytest` with `httpx` for asynchronous API testing.
- **Unit Tests**: Test `services/` logic in isolation.
- **Integration Tests**: Test `api/` endpoints using `AsyncClient`.

```bash
uv run pytest
```

## Local Development

### Prerequisites
- **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Docker**: For running PostgreSQL via `docker compose`.

### Running the App
1. **Install dependencies**:
   ```bash
   uv sync
   ```
2. **Start Database**:
   ```bash
   docker compose up -d db
   ```
3. **Run Server (Hot Reload)**:
   ```bash
   uv run uvicorn main:app --reload
   ```

### ⚠️ Port Rules — CRITICAL

**Port 5000 is reserved for `make run` (the interactive dev server). NEVER kill it.**

When you need a separate server instance for testing, scripting, or tooling, always use **port 5001**:

```bash
# ✅ CORRECT — test on port 5001, dev server stays alive on 5000:
APP_PORT=5001 uv run uvicorn main:app --host 0.0.0.0 --port 5001

# Or via .env override:
echo "APP_PORT=5001" >> .env && uv run uvicorn main:app --reload
```

When using `APP_PORT=5001`, point clients (editor, UI, scripts) at `http://localhost:5001` instead of the default `http://localhost:5000`.

### ⚠️ Never Kill Running Servers

**The dev server on port 5000 uses `--reload` and restarts on every file change. NEVER kill it.**

**NEVER run `pkill -f "uvicorn main:app"` or `pkill -f "uvicorn.*5000"` — this will kill your dev server.**

When you need a separate server instance for testing, scripting, or tooling, always use a **different port** (5001 or higher):

```bash
# ✅ CORRECT — test on port 5001, dev server stays alive on 5000:
APP_PORT=5001 uv run uvicorn main:app --host 0.0.0.0 --port 5001

# ✅ CORRECT — kill only port 5001 servers, never port 5000:
pkill -f "uvicorn.*5001"

# ❌ WRONG — kills your dev server on port 5000:
pkill -f "uvicorn main:app"      # NEVER do this
pkill -f "uvicorn.*5000"         # NEVER do this
fuser -k 5000/tcp                # NEVER do this
```

### Linting & Formatting

After making any code changes, always run:

```bash
uv run ruff check --fix app/
```

Ruff enforces style rules and formatting. It is configured in `ruff.toml`.

## Git & Commits

Use **Conventional Commits** with **Semantic Versioning**. All git operations run from within `pybpm-api/` — never in the parent workspace folder.

A Conventional Commits validator at `.githooks/commit-msg` rejects non-conforming messages automatically.

### Commit format
```
<type>(optional scope): <description>

[optional body]

[optional footer(s)]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

### Examples
- `feat(engine): add BPMN model loader for XML parsing`
- `fix(rbac): resolve permission check on case deletion`
- `chore: bump version to 1.0.0`

### Versioning rules (SemVer)
- **MAJOR** — incompatible API changes (`BREAKING CHANGE:` footer or `!` after type)
- **MINOR** — new functionality added backwards-compatibly
- **PATCH** — backward-compatible bug fixes
