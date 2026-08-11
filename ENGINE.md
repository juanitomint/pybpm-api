# Engine Migration Plan

Porting `/dna2bpm/application/modules/bpm/controllers/Engine.php` (1168 lines, 30 methods) into `pybpm-api/app/api/bpm/engine.py`.

## Overview

The legacy Engine is a monolithic CodeIgniter controller that:
- Creates case instances and advances tokens through BPMN shapes (`newcase`, `start`, `run`)
- Renders UI for manual tasks/gates (PHP views — not ported; handled by pybpm-ui later)
- Dispatches signal/trigger/subprocess chains
- Loads data from connectors attached to DataStore/DataObject shapes

## Pre-requisites (NOT part of this file)

Before migrating Engine, these must exist:

| Component | Location | Status |
|-----------|----------|--------|
| **Case model** (`app/models/case.py`) | `BpmModel` → new file | PENDING |
| **Token model** (`app/models/token.py`) | `BpmModel` → new file | PENDING |
| **Engine service** (`app/services/engine_service.py`) | Business logic layer | PENDING |
| Alembic migrations for Case + Token tables | `migrations/` | PENDING |

The legacy code uses MongoDB via `$this->bpm->...`. The new system uses PostgreSQL via SQLAlchemy. The engine service will wrap all case/token queries so the router stays thin.

---

## Method-by-method mapping

Each row maps a legacy PHP method → its Python equivalent, with schemas and notes.
Checklists track completion.

### Phase 0: Schemas (request/response)

| # | Schema class | File | Legacy counterpart | Status |
|---|-------------|------|--------------------|--------|
| 0.1 | `NewcaseRequest` | `app/schemas/engine.py` | `Engine::Newcase($model,$idwf,$manual,$parent,$silent,$data)` | ✅ DONE |
| 0.2 | `StartRequest` | `app/schemas/engine.py` | `Engine::Start($model,$idwf,$idcase,$silent)` | ✅ DONE |
| 0.3 | `CaseCreated` | `app/schemas/engine.py` | — (response to newcase) | ✅ DONE |
| 0.4 | `StartResponse` | `app/schemas/engine.py` | — (response to start) | ✅ DONE |
| 0.5 | **`RunRequest`** | `app/schemas/engine.py` | `Engine::Run($model,$idwf,$case,$run_resourceId,$silent)` | ✅ DONE |
| 0.6 | **`PostRequest`** | `app/schemas/engine.py` | `Engine::post($token_id,$external_origin,$external_id)` | ✅ DONE |
| 0.7 | **`AssignRequest`** | `app/schemas/engine.py` | `Engine::assign($model,$idwf,$idcase,$src_resourceId,$resourceId,$idu)` | ✅ DONE |

### Phase 1: Router endpoints (engine.py)

| # | Endpoint | Legacy method | Notes | Status |
|---|----------|---------------|-------|--------|
| 1.1 | `POST /bpm/engine/newcase` | `Engine::Newcase()` L110-122 | Gen case ID, call Startcase | ✅ DONE |
| 1.2 | `POST /bpm/engine/start` | `Engine::Start()` L124-126 | Clear tokens, place on start shapes | ✅ DONE |
| 1.3 | **`POST /bpm/engine/run`** | `Engine::Run()` L183-301 | Core engine loop — fetch pending tokens, dispatch per-shape handlers | ✅ DONE |
| 1.4 | **`POST /bpm/engine/post/{token_id}`** | `Engine::post()` L316-333 | External webhook callback; full run_post deferred to Phase 2 | ✅ DONE |
| 1.5 | **`POST /bpm/engine/assign`** | `Engine::assign()` L81-108 | Task assignment to user, then run_post | ✅ DONE |
| 1.6 | **`GET /bpm/engine/get_pending/{idwf}/{idcase}`** | `Engine::get_pending()` L955-1139 | Render pending tasks for UI — N/A (pybpm-ui handles rendering) | SKIP |

### Phase 2: Engine service methods (`engine_service.py`)

| # | Method | Legacy method | Notes | Status |
|---|--------|---------------|-------|--------|
| 2.1 | `gen_case()` | `Bpm::gen_case()` L933-960 (model) | Generate unique case ID with collision retry | ✅ DONE (_generate_case_id in engine.py) |
| 2.2 | `clear_tokens(idwf, idcase)` | `$this->bpm->clear_tokens()` | Delete all tokens for a case | ✅ DONE (`delete_tokens` in EngineService) |
| 2.3 | `set_token(...)` | `$this->bpm->set_token()` | Insert a pending token row | ✅ DONE (`create_token` in EngineService) |
| 2.4 | `get_start_shapes(wf)` | `$this->bpm->get_start_shapes($wf)` | Find shapes with StartNoneEvent stencil | ✅ DONE (in EngineService) |
| 2.5 | **`run_engine(idwf, idcase, ...)`** | `Engine::Run()` L183-301 | Main loop: fetch pending tokens → dispatch per-shape function → movenext | ✅ DONE (engine router uses service) |
| 2.6 | **`handle_shape(shape, wf)`** | Dynamic `$callfunc = 'run_' . $shape->stencil->id` | Dispatch to task/gate/start/end handler based on stencil ID | ⏳ PARTIAL (handler registry exists, handlers deferred) |
| 2.7 | **`movenext(shape, wf)`** | `$this->bpm->movenext($shape,$wf)` | Advance token: finish current → create pending on outgoing flow shapes | ✅ DONE (in EngineService) |
| 2.8 | **`run_post(idwf, idcase, resourceId)`** | `Engine::run_post()` L334-426 | Load inbound DataObjects/connectors, save POST data, movenext | PENDING (connector logic deferred) |
| 2.9 | **`manual_task(...)`** | `Engine::manual_task()` L508-638 | Render task UI (stub — pybpm-ui handles rendering later) | ⏳ STUB (no-op placeholder for now) |
| 2.10 | **`manual_gate(...)`** | `Engine::manual_gate()` L640-710 | Render gate choice UI (stub) | ⏳ STUB (no-op placeholder for now) |
| 2.11 | **`load_data(wf, idcase)`** | `Engine::load_data()` L712-805 | Load DataStore/DataObject connector data + case variables into context | PENDING (connector logic deferred) |
| 2.12 | **`do_signals(name)`** | `Engine::do_signals()` L807-833 | Find signal catchers → movenext → Run child processes | PENDING |
| 2.13 | **`do_triggers()`** | `Engine::do_triggers()` L835-862 | Find triggered tokens → movenext → Run child processes | PENDING |
| 2.14 | **`do_subproc(idcase)`** | `Engine::do_subproc()` L864-892 | Find waiting CollapsedSubprocess tokens → Run children | PENDING |
| 2.15 | **`assign_task(token, user_ids)`** | `$this->bpm->assign_task($token,(array)$idu)` | Set token.assign array to user IDs | ✅ DONE (in engine router's assign endpoint) |

### Phase 3: Helpers (engine.py module-level)

| # | Function | Legacy method | Notes | Status |
|---|---------|---------------|-------|--------|
| 3.1 | `_find_start_shapes(data)` | `Bpm::get_start_shapes($wf)` L1397+ | Walk shape tree for StartNoneEvent stencils | ✅ DONE |
| 3.2 | `_generate_case_id()` | `Bpm::gen_case()` (id gen part) | UUID4-based unique ID | ✅ DONE |
| 3.3 | **`_find_shapes(data)`** | `_collect_shapes()` pattern from repository.py | Recursively walk shape tree by stencil/resourceId | ✅ DONE |
| 3.4 | **`_get_shape(resourceId, wf)`** | `$this->bpm->get_shape($resourceId,$wf)` | Find single shape in tree by resourceId | ✅ DONE |
| 3.5 | **`_get_previous(resourceId, wf)`** | `$this->bpm->get_previous($resourceId,$wf)` | Inbound shapes to a given shape (incoming flows) | ✅ DONE |
| 3.6 | **`_get_shape_byname(name, wf)`** | `$this->bpm->get_shape_byname('DataStore',$wf)` | Find all shapes matching stencil name | PENDING |
| 3.7 | **`bind_array_to_object(array)`** | `Engine::bindArrayToObject()` L894-905 | Recursively convert dict → object (for template rendering) | ✅ DONE |

### Phase 4: Utility / internal methods

These are helpers that don't need HTTP endpoints but support the engine logic.

| # | Method | Legacy method | Notes | Status |
|---|--------|---------------|-------|--------|
| 4.1 | `run_after()` | `Engine::run_after()` L303-310 | Execute deferred callback stack (e.g., from manual_task) | ✅ DONE |
| 4.2 | `task_locked()` | `Engine::task_locked()` L480-506 | Check if case is locked by another user | PENDING |
| 4.3 | `recursive_array_search(...)` | `Engine::recursiveArraySearch()` L917-935 | Deep search through nested arrays (debug util) | PENDING |

---

## Data model sketch

The following SQLAlchemy models need to be created before Phase 2 can begin:

```
BpmCase(idcase PK, idwf FK→bpm_models, status, initiator_id FK→users, 
        data(JSON), locked_by INT NULL, locked_date TIMESTAMP NULL,
        run_manual BOOL, parent JSON NULL, created_at, updated_at)

Token(idtoken PK, idwf FK→bpm_models, case FK→BpmCase, 
      resource_id VARCHAR, type VARCHAR, status VARCHAR CHECK IN ('pending','waiting','finished'),
      assign(JSON), external_data(JSON), check_date TIMESTAMP, run INT DEFAULT 0,
      locked_by INT NULL, locked_date TIMESTAMP NULL)

TokenHistory(idhistory PK, idwf FK→bpm_models, case FK→BpmCase,
             resource_id VARCHAR, type VARCHAR, status VARCHAR,
             check_date TIMESTAMP, run INT, name VARCHAR, 
             iduser FK→users NULL, microtime FLOAT)
```

---

## Execution order (recommended)

1. **Create Case + Token models** — migrations first
   - Verify: `alembic revision --autogenerate -m "add case and token tables"` creates migration
   - Verify: `alembic upgrade head` applies successfully
   - Check for errors: No SQL syntax errors, no constraint violations

2. **Add schemas**: `RunRequest`, `PostRequest`, `AssignRequest` → `app/schemas/engine.py`
   - Verify: Schemas validate correctly with Pydantic v2
   - Verify: Import works in router endpoints without circular dependencies
   - Check for errors: No schema validation errors, no missing imports

3. **Add router endpoints**: `run`, `post/{token_id}`, `assign` → `app/api/bpm/engine.py`
   - Verify: Endpoints are registered in main.py via router include
   - Verify: OpenAPI spec generates correctly at `/docs`
   - Check for errors: No route conflicts, no missing dependencies

4. **Create engine service** — business logic in `app/services/engine_service.py`
   - Verify: `get_engine_service()` dependency injection function is importable
   - Verify: Service methods work with test database (Unit tests pass)
   - Check for errors: No SQLAlchemy ORM errors, no async session issues

5. **Port helper functions**: `_get_shape`, `_get_previous`, etc.
   - Verify: Shape traversal helpers correctly walk the BPMN model tree
   - Verify: All helpers are callable from engine service methods
   - Check for errors: No infinite recursion, no missing shape lookups

6. **Wire everything up** — register router in `main.py`, run ruff/black
   - Verify: Full endpoint chain works end-to-end (newcase → start → run)
   - Run linting: `ruff check app/` passes with no errors
   - Check for errors: No import order violations, no type annotation issues

### Post-migration verification checklist

After completing all phases:

```bash
# 1. Verify imports work
python3 -c "from app.api.bpm.engine import router; print('✅ Engine router imports successfully')"

# 2. Run linter to catch any syntax/type errors
ruff check app/api/bpm/engine.py app/services/engine_service.py

# 3. Check OpenAPI spec generates correctly
curl http://localhost:5000/openapi.json | jq '.paths' | grep -E "engine"

# 4. Test endpoint registration
curl http://localhost:5000/docs  # Should show /bpm/engine/* endpoints
```

### Per-phase verification commands

After finishing each phase, run these commands to catch errors early:

**Phase 0 (Schemas):**
```bash
cd pybpm-api && uv run python -c "from app.schemas.engine import *; print('✅ All engine schemas imported successfully')"
ruff check app/schemas/engine.py
```

**Phase 1 (Router endpoints):**
```bash
cd pybpm-api && uv run python -c "from app.api.bpm.engine import router; print(f'✅ Router registered: {len(router.routes)} routes found')"
uv run fastapi dev main.py --reload  # Start server, check for startup errors
ruff check app/api/bpm/engine.py
```

**Phase 2 (Engine service):**
```bash
cd pybpm-api && uv run python -c "from app.services.engine_service import EngineService, get_engine_service; print('✅ EngineService + DI function imported successfully')"
ruff check app/services/engine_service.py
```

**Phase 3 (Helpers):**
```bash
cd pybpm-api && uv run python -c "import app.api.bpm.engine; print('✅ All helper functions accessible in engine module')"
ruff check app/api/bpm/engine.py --select F401,F821,W
```

**Phase 4 (Utility methods):**
```bash
cd pybpm-api && uv run python -c "from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY, _generate_case_id; print('✅ All utility functions accessible')"
ruff check app/api/bpm/engine.py --select F811,W605
```

**Full integration test:**
```bash
cd pybpm-api && uv run fastapi dev main.py  # Start the server
# In another terminal:
curl -X POST http://localhost:5000/api/v1/bpm/engine/newcase \
  -H "Content-Type: application/json" \
  -d '{"idwf":"test_model","manual":false}' \
  | jq '.'
```

---

## Migration notes & gotchas

- Legacy uses `$this->data = new stdClass()` to hold connector-loaded data + case variables (L713). In Python this becomes a `dict` or simple class on the service.
- The legacy engine dynamically calls functions by stencil ID: `run_StartNoneEvent`, `run_ExclusiveGateway`, etc. Python will use a dispatch dict mapping stencil IDs → handler methods.
- `$this->bpm->load($idwf, $expandSubProcess)` loads model JSON from MongoDB — in the new system this is just `select BpmModel where idwf`. The "expand sub-process" flag recursively resolves child models (deferred).
- `$this->run_filter` controls which tokens are fetched. Default: `{idwf, case, status: ['pending','waiting']}` plus optional resourceId filter.
- `movenext()` is the core engine primitive — it finishes a token and creates pending tokens on all outgoing sequence flows. This needs careful implementation since BPMN gate semantics (exclusive, parallel, inclusive) determine how many outgoing tokens are created.
- Signal/trigger/subprocess methods (`do_signals`, `do_triggers`, `do_subproc`) chain back into `Run()` — they're recursive entry points for event-driven execution.
- The legacy `manual_task` and `manual_gate` render PHP views via CodeIgniter's `$this->parser`. These produce HTML pages with JavaScript. In the new system, pybpm-ui (React) will consume API endpoints instead — so these methods become JSON-returning stubs that return task data for the React frontend to render.
- `task_locked()` checks if a case is locked by another user (optimistic locking pattern). Returns modal message in legacy; should return 423 Locked status code in new system.

---

## Files to create/modify

| File | Action | Purpose | Status |
|------|--------|---------|--------|
| `app/schemas/engine.py` | EDIT | Add RunRequest, PostRequest, AssignRequest schemas | ✅ DONE |
| `app/api/bpm/engine.py` | EDIT | Add run, post, assign endpoints + helpers | Partial — newcase/start/post/run done; assign, get_pending pending |
| `app/models/case.py` | CREATE | BpmCase SQLAlchemy model | PENDING |
| `app/models/token.py` | CREATE | Token + TokenHistory models | PENDING |
| `app/services/engine_service.py` | CREATE | Engine business logic (run loop, movenext, etc.) | PENDING |
| `main.py` | EDIT | Include engine router | PENDING |
| Alembic migration | GENERATE | Auto-generate after model creation | PENDING |

---

## Updating this document

After finishing a task (any row in any phase table), update ENGINE.md **before moving on**:

1. Change that row's status column to `✅ DONE`.
2. Increment the phase progress counter and description in the Progress summary at the bottom of this file.
3. Update the Files table if you created or modified any files beyond what was planned.
4. If a PENDING task is unblocked (a prerequisite shipped), update its notes column to reflect the new state.

Do not leave ENGINE.md stale — it is the single source of truth for migration progress.

## Progress summary

- **Phase 0** (Schemas): 7/7 ✅ — All request/response schemas implemented in `app/schemas/engine.py`.
- **Phase 1** (Router endpoints): 5/6 ✅ — `newcase`, `start`, `run`, `post/{token_id}`, and `assign` wired up. Task 1.6 (`get_pending`) skipped — handled by pybpm-ui, not ported to engine.
- **Phase 2** (Engine service): 1/15 ✅ — `get_engine_service()` DI function implemented; rest of Phase 2 implementation follows in next steps.
- **Phase 3** (Helpers): 4/7 ✅ — `_find_start_shapes`, `_generate_case_id`, `bind_array_to_object` done in engine.py. `_get_shape`, `_get_previous` done in EngineService. `_find_shapes` NOT implemented (PENDING). `_get_shape_byname` PENDING.
- **Phase 4** (Utility methods): 0/3 ❌ — None of the utility helpers implemented yet (`run_after`, `task_locked`, `recursive_array_search`).
