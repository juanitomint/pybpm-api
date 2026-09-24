# PyBPM API

**Migrated PHP HMVC BPM Engine Backend** — a FastAPI service that powers the PyBPM workflow engine, model repository, and dashboard APIs.

## Architecture

### System Architecture

```mermaid
graph TB
    subgraph Clients["Clients"]
        PA[pybpm-admin<br/>Port 8080]
        PU[pybpm-ui<br/>Port 3000]
        EC[External Clients]
    end

    subgraph API["pybpm-api FastAPI (Port 5000)"]
        MW[Middleware<br/>CORS / NoCache]
        R[Router<br/>/auth / /bpm / /dashboard<br/>/inbox / /events<br/>/users / /groups<br/>/rbac / /admin]
        
        subgraph Services["Service Layer"]
            ES[EngineService]
            BS[BpmService]
            SS[SchedulerService]
            IS[InboxService]
            MS[ModelService]
        end
        
        subgraph Handlers["Handler Layer"]
            FH[Flow Handlers]
            GH[Gate Handlers]
            TH[Task Handler]
            EH[Event Handlers]
            SE[Start/End Handlers]
            SH[Subprocess Handler]
        end
        
        subgraph Persistence["Persistence"]
            DB[(PostgreSQL<br/>/ SQLite)]
            SVG[(SVG Files)]
            SCH[APScheduler<br/>60s poll]
        end
        
        MW --> R
        R --> Services
        Services --> Handlers
        Handlers --> DB
        Handlers --> SVG
        SCH --> SS
    end

    PA -->|HTTP JSON| API
    PU -->|HTTP JSON| API
    EC -->|HTTP JSON| API
```

### Token Lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running: engine.run()
    running --> user: TaskHandler (User/Manual)
    running --> waiting: Timer/Message event
    running --> done: EndNoneEvent
    running --> cancelled: EndCancelEvent
    running --> error: EndErrorEvent
    user --> validating: validate_task
    validating --> done: task_done
    waiting --> running: scheduler dispatch
    user --> running: post_task
    done --> [*]
    cancelled --> [*]
    error --> [*]
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI (async), Starlette |
| ORM | SQLAlchemy 2.0 (async with `asyncpg` / `aiosqlite`) |
| Migrations | Alembic |
| Scheduler | APScheduler (BackgroundScheduler, 60s poll) |
| Auth | python-jose (JWT HS256), passlib/bcrypt |
| Server | uvicorn |
| Database | PostgreSQL (production), SQLite (dev) |
| Testing | pytest, pytest-asyncio, httpx, pytest-xdist |
| Linting | Ruff |

## Project Structure

```
pybpm-api/
├── main.py                  # FastAPI app, middleware, router wiring
├── extensions.py            # Async engine/session factories, DB deps
├── config.py                # Pydantic-settings-style Config class
├── pyproject.toml           # Dependencies + tool config
├── Dockerfile               # Multi-stage: python:3.14-slim + uv
├── docker-compose.yml       # App + PostgreSQL service
├── boot.sh                  # Startup: db migration → uvicorn
├── init.sql                 # Initial DB schema
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
│   │   │   ├── tokens.py    # Token manager endpoints (prefix: /bpm/token_manager)
│   │   │   └── event_schedule.py  # Scheduled events (prefix: /events/schedules)
│   │   ├── dashboard.py    # Case/task counts, task lifecycle (lock/unlock/validate/done)
│   │   ├── inbox.py        # Inbox message filtering, CRUD
│   │   ├── groups.py       # Group CRUD (prefix: /groups)
│   │   ├── users.py        # User CRUD (prefix: /users)
│   │   ├── profile.py      # User profile (prefix: /users, mounted with users_router)
│   │   └── rbac.py         # RBAC management (prefix: /rbac)
│   ├── core/
│   │   ├── logging.py       # Uvicorn log config builder
│   │   └── scheduler.py     # APScheduler start/stop
│   ├── handlers/
│   │   ├── __init__.py      # Auto-registration of all handlers
│   │   ├── flow.py          # SequenceFlow, MessageFlow, _safe_eval
│   │   ├── gate.py          # ParallelGateway, ExclusiveDatabasedGateway, EventbasedGateway
│   │   ├── task.py          # User/Manual/Script/Send/Receive task types
│   │   ├── event.py         # Intermediate events (timer, message, signal, error, etc.)
│   │   ├── start_end.py     # StartNone/Message/Timer, EndNone/Message/Error/Cancel/Terminate
│   │   ├── subproc.py       # CollapsedSubprocess (child case delegation)
│   │   └── eval_context.py  # Script execution namespace builder
│   ├── models/
│   │   ├── base.py          # SQLAlchemy DeclarativeBase
│   │   ├── bpm_model.py     # BpmModel — BPMN model JSON + SVG storage
│   │   ├── case.py          # BpmCase — case instance (parent/child hierarchy)
│   │   ├── token.py         # Token, TokenHistory — workflow execution tokens
│   │   ├── user.py          # User
│   │   ├── group.py         # Group
│   │   ├── user_group.py    # UserGroup
│   │   ├── permission_group.py
│   │   ├── permission_repository.py
│   │   ├── message.py       # Message — inbox items
│   │   ├── signal.py        # Signal definitions
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
│   │   └── __init__.py
│   └── services/
│       ├── engine_service.py  # Core engine: token lifecycle, shape dispatch, movenext
│       ├── bpm_service.py     # gen_case, startcase, subprocess orchestration
│       ├── scheduler_service.py # Due schedule dispatch
│       ├── inbox_service.py   # Inbox message operations
│       ├── model_service.py   # Model CRUD operations
│       ├── signal_service.py
│       ├── user_service.py
│       ├── group_service.py
│       ├── rbac_service.py
│       └── profile_service.py
├── tests/
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
│   └── test_event_schedule_api.py
├── tools/
│   ├── seed_models.py
│   ├── seed_tasktype.py
│   ├── seed_users.py
│   └── test_model*.py
└── files/
    └── images/
        ├── model/
        ├── svg/
        └── zip/           # BPMN model archives (test cases)
```

## BPM Engine Architecture

The engine processes BPMN 2.0 models by dispatching tokens through a registry of shape handlers. Each shape type has a dedicated handler class that implements the BPMN semantics.

### Shape Handler Registry

```mermaid
graph LR
    HR[ENGINE_HANDLER_REGISTRY<br/>stencil_id → handler]
    
    HR --> Start[Start/End Handlers]
    HR --> Gate[Gate Handlers]
    HR --> Event[Event Handlers]
    HR --> Flow[Flow Handlers]
    HR --> Task[Task Handler]
    HR --> Subproc[Subprocess Handler]
    
    Start --> SN[StartNoneEvent]
    Start --> SM[StartMessageEvent]
    Start --> ST[StartTimerEvent]
    Start --> SG[GenericStart*]
    
    Gate --> PG[ParallelGateway]
    Gate --> EG[ExclusiveDBGateway]
    Gate --> GB[EventbasedGateway]
    Gate --> GG[GenericGateway*]
    
    Event --> ITE[IntermediateTimerEvent]
    Event --> IME[IntermediateMessageEvent]
    Event --> ISG[IntermediateSignalEvent]
    Event --> IER[IntermediateErrorEvent]
    Event --> ICE[IntermediateConditionalEvent]
    Event --> IMT[IntermediateMessageThrowing]
    Event --> ILT[IntermediateLinkThrowing]
    Event --> IST[IntermediateSignalThrowing]
    
    Flow --> SF[SequenceFlow]
    Flow --> MF[MessageFlow]
    
    Task --> TK[Task<br/>User/Manual/Script/Send/Receive]
    
    Subproc --> CS[CollapsedSubprocess]
    Subproc --> IS[InlineSubprocess]
```

### Engine Execution Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as API Router
    participant ES as EngineService
    participant HR as Handler Registry
    participant DB as Database

    Client->>API: POST /bpm/engine/run/{idwf}/{idcase}
    API->>DB: Load model + case
    DB-->>API: model JSON, case data
    
    loop Engine Loop (iterative)
        API->>ES: find pending tokens
        ES->>DB: query tokens where status='pending'
        DB-->>ES: pending tokens
        
        loop For each token
            ES->>HR: lookup handler by stencil_id
            HR-->>ES: ShapeHandler class
            ES->>HR: handler.handle(token, shape, service)
            
            alt handler returns True (consumed)
                Note over ES,HR: Token processed, no movenext
            else handler returns False
                ES->>DB: movenext token
                DB-->>ES: updated tokens
            end
        end
        
        ES->>DB: persist token state
    end
    
    API-->>Client: RunResponse {ok: true}
```

### Handler Interface

Each handler implements a standard interface:

```python
class ShapeHandler:
    STENCIL_ID: str  # BPMN stencil ID (e.g. "ParallelGateway")

    async def handle(
        self,
        token: Token,  # Current token being processed
        shape: dict,  # Shape data from model JSON
        service: EngineService,  # DB access + engine utilities
    ) -> bool:
        """
        Returns True if the handler consumed the token (no movenext needed).
        Returns False if the handler wants the engine to call movenext.
        """
        ...
```

### Key BPMN Constructs Supported

| Construct | Handler | Notes |
|-----------|---------|-------|
| StartNoneEvent | `StartNoneEventHandler` | Default start |
| StartMessageEvent | `StartMessageEventHandler` | Waits for message |
| StartTimerEvent | `StartTimerEventHandler` | Time-based trigger |
| EndNoneEvent | `EndNoneEventHandler` | Normal completion |
| EndMessageEvent | `EndMessageEventHandler` | Throws message |
| EndErrorEvent | `EndErrorEventHandler` | Error termination |
| EndCancelEvent | `EndCancelEventHandler` | Cancel subcases |
| EndTerminateEvent | `EndTerminateEventHandler` | Hard terminate |
| ParallelGateway | `ParallelGatewayHandler` | Split/join parallel |
| ExclusiveDBGateway | `ExclusiveDatabasedGatewayHandler` | Data-based branching |
| EventbasedGateway | `EventbasedGatewayHandler` | Event-based split |
| SequenceFlow | `SequenceFlowHandler` | Default flow |
| MessageFlow | `MessageFlowHandler` | Message flow |
| UserTask | `TaskHandler` | Status='user', waits for POST |
| ManualTask | `TaskHandler` | Status='user' |
| ScriptTask | `TaskHandler` | Eval Python script, movenext |
| SendTask | `TaskHandler` | movenext (deferred dispatch) |
| ReceiveTask | `TaskHandler` | Waits for message |
| CollapsedSubprocess | `CollapsedSubprocessHandler` | Creates child case |
| IntermediateTimerEvent | `IntermediateTimerEventHandler` | Timer wait |
| IntermediateMessageEvent* | `IntermediateMessageEvent*Handler` | Message wait/throw |
| IntermediateSignalEvent* | `IntermediateSignalEvent*Handler` | Signal wait/throw |
| IntermediateErrorEvent | `IntermediateErrorEventHandler` | Error catching |
| IntermediateConditionalEvent | `IntermediateConditionalEventHandler` | Condition check |
## API Endpoints

> **Prefix note**: The auth router is mounted with `/api/v1` prefix; all other routers use their own prefix directly under the FastAPI root (`/`).

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/token` | Login (OAuth2 password flow) |
| GET | `/api/v1/auth/me` | Get current user |

### BPM Repository

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/bpm/repository/save` | Save/update model |
| POST | `/bpm/repository/save_as` | Save as new model |
| POST | `/bpm/repository/duplicate` | Clone model |
| POST | `/bpm/repository/add/{idwf}` | Create empty model scaffold |
| GET | `/bpm/repository/load/model/{idwf}` | Load model data |
| GET | `/bpm/repository/dump/model/{idwf}` | Dump model + metadata |
| DELETE | `/bpm/repository/delete` | Delete model |
| GET | `/bpm/repository/svg/{idwf}` | Serve model SVG |
| GET | `/bpm/repository/get_shapes/model/{idwf}` | Get shape metadata |
| GET | `/bpm/repository/get_comments/model/{idwf}/{resource_id}` | Get shape documentation |
| POST | `/bpm/repository/import` | Import model from zip |
| POST | `/bpm/repository/update_folder` | Move model to folder |
| GET | `/bpm/repository/check_model/{name}` | Check model name uniqueness |
| POST | `/bpm/repository/save_script/{idwf}/{resource_id}` | Save script |
| POST | `/bpm/repository/save_model/{idwf}` | Persist data + SVG payload |
| GET | `/bpm/repository/thumbnail/{idwf}/{width}/{height}` | Thumbnail |
| GET | `/bpm/repository/tokens/{idwf}/{idcase}/{filter_status}` | Get tokens |
| POST | `/bpm/repository/get_tree2/{output_format}` | Build model tree (ExtJS format) |

### BPM Engine

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/bpm/engine/newcase` | Create new case instance |
| POST | `/bpm/engine/start` | Start/resume case at start shapes |
| POST | `/bpm/engine/run/{idwf}/{idcase}` | Execute engine loop |
| POST | `/bpm/engine/post/{idwf}/{idcase}/{resource_id}` | POST data to waiting task (path-based lookup) |
| POST | `/bpm/engine/post/{token_id}` | POST data to waiting task (legacy token-ID lookup) |
| POST | `/bpm/engine/assign` | Assign task to users |
| POST | `/bpm/engine/gate/{idwf}/{idcase}/{resource_id}` | Manual gateway decision |
| POST | `/bpm/engine/task/{idwf}/{idcase}/{resource_id}` | Complete manual task |

### Case Manager

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/bpm/case_manager` | List cases |
| GET | `/bpm/case_manager/{idcase}` | Get case by ID |
| PATCH | `/bpm/case_manager/{idcase}` | Update case |
| DELETE | `/bpm/case_manager/{idcase}` | Delete case |
| POST | `/bpm/case_manager/{idcase}/freez` | Freeze case |
| GET | `/bpm/case_manager/data/read/{idwf}` | Read case data |
| GET | `/bpm/case_manager/search/{status}` | Search cases by status |
| GET | `/bpm/case_manager/tokens/status/{idwf}/{idcase}` | Get token statuses |
| POST | `/bpm/case_manager/revert/model/{idwf}/{idcase}/{resource_id}` | Revert model change |

### Token Manager

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/bpm/token_manager/{resource_id}` | Get token by resource ID |
| GET | `/bpm/token_manager/tokens/{idwf}/{case_id}` | List tokens for case |
| GET | `/bpm/token_manager/status/{idwf}/{idcase}` | Get token status summary |
| POST | `/bpm/token_manager/create/{idwf}/{case_id}` | Create token |
| POST | `/bpm/token_manager/assign/{idwf}/{case_id}/{resource_id}` | Assign token |
| PATCH | `/bpm/token_manager/update/{idwf}/{case_id}/{resource_id}` | Update token |
| DELETE | `/bpm/token_manager/delete/{idwf}/{case_id}/{resource_id}` | Delete token |

### Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/dashboard/cases` | Paginated case list |
| GET | `/dashboard/cases/count` | Open/closed case counts |
| GET | `/dashboard/tasks` | Paginated task list |
| GET | `/dashboard/tasks/count` | Token counts by status |
| PATCH | `/dashboard/tasks/done` | Complete a task |
| PATCH | `/dashboard/tasks/lock` | Lock a task |
| PATCH | `/dashboard/tasks/unlock` | Unlock a task |
| PATCH | `/dashboard/tasks/validate` | Validate a task |

### Inbox

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/inbox` | List messages |
| POST | `/inbox/filter/` | Filter messages by folder/status |
| GET | `/inbox/message/{msgid}/` | Get single message |
| PATCH | `/inbox/message/{msgid}/` | Update message |
| PUT | `/inbox/message/{msgid}/read` | Mark as read |
| PUT | `/inbox/message/{msgid}/unread` | Mark as unread |
| PUT | `/inbox/message/{msgid}/star` | Toggle star |
| DELETE | `/inbox/message/{msgid}/` | Move to trash |
| POST | `/inbox/send/` | Send message |
| POST | `/inbox/counts/` | Message counts by folder |
| GET | `/inbox/users` | Search users |

### Event Schedule

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/events/schedules` | List scheduled events |
| POST | `/events/schedules` | Create schedule entry |
| GET | `/events/schedules/{idschedule}` | Get schedule entry |
| PATCH | `/events/schedules/{idschedule}` | Update schedule entry |
| DELETE | `/events/schedules/{idschedule}` | Delete schedule entry |

### Users

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users` | List users |
| POST | `/users` | Create user |
| GET | `/users/{idu}` | Get user by ID |
| PUT | `/users/{idu}` | Update user |
| DELETE | `/users/{idu}` | Delete user |
| GET | `/users/count` | User count |
| GET | `/users/profile` | Get current user profile |
| PUT | `/users/profile` | Update current user profile |

### Groups

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/groups` | List groups |
| POST | `/groups` | Create group |
| GET | `/groups/{idgroup}` | Get group by ID |
| PUT | `/groups/{idgroup}` | Update group |
| DELETE | `/groups/{idgroup}` | Delete group |
| GET | `/groups/count` | Group count |

### RBAC

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/rbac/paths` | List RBAC paths |
| PUT | `/rbac/paths` | Update RBAC paths |
| GET | `/rbac/repository` | List repository permissions |
| POST | `/rbac/repository` | Create repository permission |
| DELETE | `/rbac/repository` | Delete repository permission |
| PUT | `/rbac/repository/` | Update repository permission |
| GET | `/rbac/repository/root` | Get repository root |
| POST | `/rbac/repository/root` | Set repository root |
| PUT | `/rbac/repository/root` | Update repository root |

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/health` | Health check |

## Configuration

All settings via environment variables (loaded from `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./pybpm.db` | Database connection string |
| `SECRET_KEY` | *(required)* | JWT signing key |
| `JWT_EXPIRATION_HOURS` | `24` | Token lifetime |
| `ADMIN_GROUP_ID` | `1` | Admin group ID |
| `AUTODISCOVER_PATHS` | `false` | Auto-discover model paths |
| `LOG_LEVEL` | `INFO` | Logging level |
| `APP_ENV` | `development` | Environment (development/production/testing) |
| `SQL_DEBUG` | `true` (dev only) | SQLAlchemy echo |

## Development

```bash
# Install dependencies
uv sync

# Run with SQLite (dev)
APP_ENV=development uv run uvicorn main:app --reload --port 5000

# Run with PostgreSQL (production)
docker compose up -d
APP_ENV=production uv run uvicorn main:app --reload --port 5000
```

### Testing

```bash
# Run all tests
uv run pytest

# Run with parallel workers
uv run pytest -n auto

# Run with coverage
uv run pytest --cov=app --cov-report=html
```

### Docker

```bash
# Start app + PostgreSQL
docker compose up -d

# Stop
docker compose down
```

## Database Schema

The application uses SQLAlchemy models mapped to PostgreSQL tables:

- `bpm_model` — BPMN model definitions (JSON data + SVG)
- `bpm_case` — Case instances (with parent/child hierarchy via `parent_json`)
- `token` — Workflow execution tokens (lifecycle: pending → running → user/waiting/done)
- `token_history` — Token state history
- `user` / `group` / `user_group` — User management
- `permission_group` / `permission_repository` — RBAC
- `message` — Inbox messages
- `signal` — Signal definitions
- `event_schedule` — Scheduled event triggers

## Design Decisions

1. **Async-first**: All endpoints use `async def` with `asyncpg`/`aiosqlite` for non-blocking I/O.
2. **Handler registry pattern**: Shape handlers are auto-registered at import time via module-level calls to `ENGINE_HANDLER_REGISTRY.register()`. This eliminates explicit import wiring and makes adding new handlers trivial.
3. **Service layer separation**: Business logic is extracted into service classes (`EngineService`, `BpmService`, etc.) rather than inline in routers.
4. **Legacy compatibility**: API endpoints mirror the PHP `Repository` and `Engine` class contracts exactly — same URLs, same request/response shapes. This allows the ExtJS admin UI and Oryx editor to work unchanged.
5. **SQLite default**: Development defaults to SQLite for zero-dependency local runs; production requires PostgreSQL via `docker-compose.yml`.
6. **APScheduler for events**: A `BackgroundScheduler` polls `event_schedules` every 60 seconds, dispatching due timer-triggered events to waiting tokens.
7. **Script evaluation**: Task scripts are evaluated as Python expressions via `ast.parse` + `eval` with a restricted namespace (`__builtins__` empty).
