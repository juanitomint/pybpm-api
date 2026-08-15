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
├── main.py                 # FastAPI application entry point
├── config.py               # Pydantic Settings (loads from .env)
├── extensions.py           # Shared instances (e.g., SQLAlchemy engine/session)
│
├── app/
│   ├── api/                # FastAPI Routers (Endpoints)
│   │   ├── __init__.py
│   │   ├── auth.py         # Auth & Identity endpoints
│   │   └── bpm/            # BPM core logic (one controller per file)
│   │       ├── __init__.py
│   │       └── repository.py  # Model CRUD, mirrors Repository.php
│   ├── models/             # SQLAlchemy ORM Models
│   │   ├── __init__.py
│   │   ├── base.py         # DeclarativeBase
│   │   ├── bpm_model.py    # BPMN model definitions
│   │   └── user.py         # User accounts
│   ├── schemas/            # Pydantic Models (Request/Response)
│   │   ├── __init__.py
│   │   └── repository.py   # Model request/response schemas
│   ├── services/           # Business Logic (Service Layer)
│   │   ├── __init__.py
│   │   └── model_service.py  # BPMN model business logic
│   └── core/               # Security, Constants, Utilities
│       └── auth.py         # JWT bearer dependency
│
├── migrations/              # Alembic migration files
│   ├── env.py
│   └── versions/
│
├── conftest.py             # Root async test fixtures
├── alembic.ini             # Alembic configuration
├── pyproject.toml          # Project dependencies and tools
└── .env                    # Environment variables (not committed)
```

Note: `case.py`, `auth_service.py`, and `case_service.py` will be added when the Case Manager component is ported from legacy PHP. The BPM Engine, RBAC service, and Scheduler components are also pending migration from the legacy `dna2bpm/application/modules/bpm/` codebase.

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

### Testing (non-interactive)
Use `APP_PORT=5001` when running the server for testing, scripting, or tooling — keeps it off port 5000 so `make run` can stay attached to an interactive console without conflict.

```bash
# Run on port 5001 (does not block make run / port 5000)
APP_PORT=5001 uv run uvicorn main:app --host 0.0.0.0 --port 5001

# Or via .env override:
echo "APP_PORT=5001" >> .env && uv run uvicorn main:app --reload
```

When using `APP_PORT=5001`, point your clients (editor, UI, scripts) at `http://localhost:5001` instead of the default 5000.
## Linting & Formatting

After making any code changes, always run:

```bash
uv run ruff check --fix app/
uv run black app/
```

Ruff enforces style rules; Black formats the code. Both must pass before considering work complete. Ruff and Black are configured in `pyproject.toml`.

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
```
