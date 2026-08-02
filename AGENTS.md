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
pybpm/
├── main.py                 # FastAPI application entry point
├── config.py               # Pydantic Settings (loads from .env)
├── extensions.py           # Shared instances (e.g., SQLAlchemy engine/session)
│
├── app/
│   ├── api/                # FastAPI Routers (Endpoints)
│   │   ├── __init__.py
│   │   ├── auth.py         # Auth & Identity endpoints
│   │   └── bpm.py          # BPM core logic endpoints
│   ├── models/             # SQLAlchemy ORM Models
│   │   ├── __init__.py
│   │   ├── base.py         # DeclarativeBase
│   │   └── case.py         # Case entities
│   ├── schemas/            # Pydantic Models (Request/Response)
│   │   ├── __init__.py
│   │   ├── auth.py         # Auth schemas
│   │   └── case.py         # Case schemas
│   ├── services/           # Business Logic (Service Layer)
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   └── case_service.py
│   └── core/               # Security, Constants, Utilities
│
├── migrations/              # Alembic migration files
│   ├── env.py
│   └── versions/
│
├── tests/                  # Pytest suite
│   ├── conftest.py         # Async test fixtures
│   └── test_api.py         # API integration tests
│
├── alembic.ini             # Alembic configuration
├── pyproject.toml          # Project dependencies and tools
└── .env                    # Environment variables (not committed)
```

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
async def create_case(case_in: CaseCreate, service: CaseService = Depends(get_case_service)):
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

## Linting & Formatting

After making any code changes, always run:

```bash
uv run ruff check --fix app/
uv run black app/
```

Ruff enforces style rules; Black formats the code. Both must pass before considering work complete. Ruff and Black are configured in `pyproject.toml`.

## Git & Commits
Use **Conventional Commits**:
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `docs`: Documentation changes
- `test`: Adding/fixing tests
```
