# Repository API — Implementation Plan

## Overview

This document describes how to implement the BPM Model Repository CRUD API by porting all endpoints from `dna2bpm/application/modules/bpm/controllers/Repository.php` (690 lines, PHP CodeIgniter) into a FastAPI Python service. The goal is a drop-in replacement for the existing repository controller — same HTTP contract, new stack (FastAPI + SQLAlchemy + PostgreSQL).

---

## Architecture Decisions

| Aspect | Decision |
|--------|----------|
| Framework | **FastAPI** with async routes (`async def`) |
| Auth | JWT Bearer tokens via `python-jose` (already in pyproject.toml) 
| ORM | SQLAlchemy 2.0 async (`AsyncSession`) |
| DB | PostgreSQL (or SQLite for dev/tests, per existing config.py pattern) |
| File uploads | Multipart form data with `python-multipart` for zip upload/extract |
| SVG storage | **File system only** at `pybpm/static/svg/{idwf}.svg`. The DB never stores SVG content — the path is reconstructed from `{idwf}` whenever an SVG endpoint is called. |
| Project layout | Nested `app/` package: routers at `app/api/bpm.py`, models under `app/models/`, schemas under `app/schemas/repository.py`, services under `app/services/model_service.py` |

### Implementation Notes

**Always lint and format after finishing a step.** Run `uv run ruff check --fix app/ && uv run black app/` before marking any step complete. Also start the dev server (`uv run uvicorn main:app --reload`) to confirm it boots without import errors, Pydantic schema failures, or OpenAPI generation crashes. If you change models, schemas, routers, or services — especially anything that touches `extensions.py`, `config.py`, or FastAPI dependencies — a full server restart is the only reliable way to catch wiring issues early (circular imports, missing drivers, unresolved forward references, dependency injection misconfiguration).

---

## Progress Tracker

<!-- Agents: check off [x] each item as it's completed. Pick up where the last unchecked box is. -->

### 0. Scaffolding & Infrastructure
- [x] Add `python-multipart` dependency to pyproject.toml (for multipart form uploads)
- [x] Create `pybpm/static/svg/` directory (auto-created at startup if missing)
- [x] Add Alembic migration to drop `svg TEXT` column from `bpm_models` table
- [x] Update existing conftest.py / test fixtures for repository tests

### 1. Data Layer
- [x] Create `app/models/base.py` with `Base(DeclarativeBase)` exposing `.metadata` for Alembic
- [x] Create `app/models/bpm_model.py` with `BpmModel` — no `svg` column, `svg_path` property returns `static/svg/{idwf}.svg`
- [x] Create `app/models/user.py` — `User` model matching legacy migration schema (`idu`, `nick`, `pass_hash`, etc.)
- [x] Create `extensions.py` — shared sync engine (Alembic) + async engine (FastAPI) with aiosqlite support for SQLite URLs
- [x] Wire `get_async_db()` FastAPI dependency in extensions
- [x] Create `app/schemas/repository.py` with all Pydantic request/response models:
  - **Request**: `ModelCreate`, `ModelUpdate`, `ModelDuplicateRequest`, `SaveAsRequest`, `FolderUpdate`, `ScriptRequest`, `SaveModelRequest`
  - **Response**: `ModelRead` (no svg field), `CheckResponse`, `DumpResponse`, `ShapesResponse`, `CommentsResponse`, `SaveResponse`, `ModelCreateResponse`

### 2. Auth Dependency
- [x] Create FastAPI JWT bearer dependency (`get_current_user`) using `python-jose` — see `app/core/auth.py`
- [x] Wire async engine to use asyncpg driver for Postgres URLs (see `extensions.py:_async_database_url`)
- [x] Make `get_model_service()` depend on `get_async_db()` so FastAPI resolves the chain correctly

### 3. Core Endpoints (CRUD)
- [x] Step 1: PUT `/api/v1/models/save/{idwf}` — save/update model + write SVG to disk
- [x] Step 2: POST `/api/v1/models/duplicate` — clone to new idwf
- [x] Step 3: POST `/api/v1/models/save_as` — save as new model with custom title (derived from `body.title`)
- [ ] Step 4: POST `/api/v1/models/add/{idwf}` — create brand-new empty scaffold

### 4. Read / Query Endpoints
- [x] Step 5: GET `/api/v1/models/check_model/{name}` — check existence (for editor validation)
- [x] Step 6: DELETE `/api/v1/models/delete` — delete model by idwf (idwf from POST body)
- [x] Step 7: GET `/api/v1/models/load/{idwf}` — load full model data (primary read, template fallback; `?mode=` and `?debug=` query params)
- [ ] Step 8: GET `/api/v1/models/dump/{idwf}` — debug dump with expand flag (`?expand=` query param)

### 5. Save Variant Endpoints
- [x] Step 9: POST `/api/v1/models/save_script/{idwf}/{resource_id}` — save script (no-op stub; legacy re-saves full model state)
- [x] Step 10: POST `/api/v1/models/save_model/{idwf}` — save data payload with current SVG from disk

### 6. SVG / Visual Endpoints
- [x] Step 11: GET `/api/v1/models/thumbnail/{idwf}/{width}/{height}` — stub (returns raw SVG, thumbnail gen deferred)
- [ ] Step 12: GET `/api/v1/models/svg/{idwf}` — return formatted SVG from file on disk

### 7. Shape / Comment Endpoints
- [x] Step 13: GET `/api/v1/models/get_shapes/{idwf}/{debug}` — get all diagram shapes indexed by resourceId (stub; `?debug=` query param)
- [x] Step 14: GET `/api/v1/models/get_comments/{idwf}/{resource_id}` — get shape documentation/comments (stub)

### 8. Import / Bulk Operations
- [ ] Step 15: POST `/api/v1/models/import` — upload + import `.zip` model archive (multipart)

### 9. Folder Management
- [x] Step 16: GET `/api/v1/models/tokens/{idwf}/{idcase}/{filter_status}` — case token inspection (stub; moved from legacy Repository controller, will migrate to Case Manager router later)
- [ ] POST `/api/v1/models/update_folder` — move model into different folder (HTML tag sanitization stub; idwf/folder from POST body)

> **Note:** `tokens()` was in the legacy Repository controller but belongs conceptually to the Case Manager. It is listed here as step 16 since it lives in the same endpoint file. Will be moved when the Case Manager component is implemented.

### 10. Tests
- [ ] Write integration tests in `pybpm/tests/test_repository.py` covering all 16 endpoints (~50 test functions)
- [ ] Run full test suite: `uv run pytest` and confirm all green

---

**Order of implementation**: Scaffolding → Data Layer → Auth → Core CRUD (Steps 1-4) → Read/Query (5-8) → Save Variants (9-10) → SVG (11-12) → Shapes/Comments (13-14) → Import (15) → Folder (16) → Tests

## Existing Infrastructure Already in Place

From the initial Alembic migration (`2026_07_13_0031-380f18722a18_initial_schema.py`):
- **`bpm_models`** table: `idwf` (PK, TEXT), `folder` (TEXT), `version` (SMALLINT), `svg` (**TEXT — to be dropped**), `data` (JSONB), `created_at`, `updated_at`, `created_by` (FK → users)
- **`users`** table: `idu` (PK), `nick`, `pass_hash`, `name`, `lastname`, `email`, etc.

> The `svg TEXT` column in the legacy migration must be dropped — SVGs now live on disk at `pybpm/static/svg/{idwf}.svg`.
- **`case_instances`**, **`tokens`**, **`groups`**, **`permissions`** tables exist but not in scope for this phase

---

## Endpoint Mapping Table

All routes follow CodeIgniter convention: function name = first URL segment, parameters = subsequent segments. PHP `$model` parameter is implicit (always present in legacy routing) and omitted from new routes since it carries no data.

| # | PHP Method | Legacy URL Pattern | New Route (FastAPI) | Notes |
|---|-----------|-------------------|---------------------|-------|
| 1 | `save()` | `/repository/save` | **PUT** `/api/v1/models/save/{idwf}` | idwf from path; data+svg in body. Legacy extracts `$idwf = $data->resourceId`. |
| 2 | `duplicate()` | `/repository/duplicate` | **POST** `/api/v1/models/duplicate` | Both idwf + new_idwf in POST body. |
| 3 | `save_as()` | `/repository/save_as` | **POST** `/api/v1/models/save_as` | title from POST; data+svg in body. |
| 4 | `add($new_idwf=null)` | `/repository/add/{idwf}` | **POST** `/api/v1/models/add/{idwf}` | idwf optional in URL (legacy reads from POST if missing). Creates scaffold with defaults. |
| 5 | `check_model($name)` | `/repository/check_model/{name}` | **GET** `/api/v1/models/check_model/{name}` | Returns `{ok: bool}` — true if NOT taken. |
| 6 | `delete()` | `/repository/delete` | **DELETE** `/api/v1/models/delete` | idwf from POST body (no URL param). |
| 7 | `load($model, $idwf, $mode='', $debug=false)` | `/repository/load/{idwf}/{mode}/{debug}` | **GET** `/api/v1/models/load/{idwf}` + `?mode=` + `?debug=` | Optional mode/debug as query params (FastAPI can't do optional trailing path segments). |
| 8 | `edit()` | `/repository/edit/{model}/{idwf}` | *(removed — served by frontend SPA)* | Returns XHTML page, not an API endpoint. |
| 9 | `dump($model, $idwf, $expand=false)` | `/repository/dump/{idwf}/{expand}` | **GET** `/api/v1/models/dump/{idwf}` + `?expand=` | Optional expand as query param. |
| 10 | `json_view()` | `/repository/json_view/{model}/{idwf}` | *(removed — frontend view)* | Renders a JS-powered JSON editor page. Not an API endpoint. |
| 11 | `save_script($idwf, $resourceId)` | `/repository/save_script/{idwf}/{resourceId}` | **POST** `/api/v1/models/save_script/{idwf}/{resource_id}` | Re-saves full model state (stub). |
| 12 | `save_model($idwf)` | `/repository/save_model/{idwf}` | **POST** `/api/v1/models/save_model/{idwf}` | idwf from URL path; data+svg in body. |
| 13 | `thumbnail($idwf, $width, $heigth)` | `/repository/thumbnail/{idwf}/{width}/{height}` | **GET** `/api/v1/models/thumbnail/{idwf}/{width}/{height}` | All three params as path segments. |
| 14 | `svg($idwf)` | `/repository/svg/{model}/{idwf}` | **GET** `/api/v1/models/svg/{idwf}` | Returns SVG content with XML headers. |
| 15 | `get_shapes($model, $idwf, $debug=false)` | `/repository/get_shapes/{idwf}/{debug}` | **GET** `/api/v1/models/get_shapes/{idwf}/{debug}` + `?debug=` | Optional debug as query param. |
| 16 | `view()` | `/repository/view/{model}/{idwf}` | *(removed — frontend view)* | Renders the model viewer page. Not an API endpoint. |
| 17 | `tokens($model, $idwf, $idcase, $filter_status="")` | `/repository/tokens/{idwf}/{idcase}/{filter_status}` | **GET** `/api/v1/models/tokens/{idwf}/{idcase}/{filter_status}` | Case token inspection (stub). |
| 18 | `get_comments($model, $idwf, $resourceId)` | `/repository/get_comments/{idwf}/{resource_id}` | **GET** `/api/v1/models/get_comments/{idwf}/{resource_id}` | Shape documentation/comments. |
| 19 | `upload()` | GET/POST `/repository/upload` | *(removed — UI form)* | Shows upload HTML form. Frontend handles file picking. |
| 20 | `Import($model)` | `/repository/import` | **POST** `/api/v1/models/import` | Zip file upload + extract (stub). |
| 21 | `import_test()` | GET `/repository/import_test` | *(removed — dev only)* | Dev-only batch import. Not shipped to production. |
| 22 | `update_folder()` | `/repository/update_folder` | **POST** `/api/v1/models/update_folder` | idwf + folder from POST body (no URL params). |
| 23 | `repair_stencil_path()` | GET (dev-only) | *(removed — one-time migration)* | Fixes broken stencilset URLs. Not an API endpoint. |

### Summary: 17 actionable endpoints to implement

The table above removes UI-only endpoints (`edit`, `json_view`, `view`, `upload`, `import_test`) and dev-migration endpoints (`repair_stencil_path`). The remaining **17 RESTful endpoints** are listed below with implementation steps.

---

## Implementation Steps — Per Endpoint

### Data Models (SQLAlchemy)

Before writing any routes, define the model class:

```python
# repository_models.py (or app/models/bpm_model.py)
from pathlib import Path
from sqlalchemy import Column, String, Text, SmallInteger, DateTime, Integer, ForeignKey
from sqlalchemy.orm import relationship
from extensions import db  # DeclarativeBase instance

SVG_DIR = Path(__file__).parent.parent / "static" / "svg"


class BpmModel(db.Model):
    __tablename__ = "bpm_models"

    idwf = Column(String(255), primary_key=True)          # model identifier (unique key)
    folder = Column(String(255), nullable=False, default="General")
    version = Column(SmallInteger, nullable=False, default=0)
    data = Column(db.JSON, nullable=True)                  # BPMN stencil data (JSONB in PG)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    created_by = Column(Integer, ForeignKey("users.idu"), nullable=True)

    author = relationship("User", backref="models", foreign_keys=[created_by])

    @property
    def svg_path(self) -> Path:
        """Reconstruct SVG file path from idwf. No DB column needed."""
        return SVG_DIR / f"{self.idwf}.svg"
```

**Key change**: `svg TEXT` column removed. SVGs live exclusively as files at `pybpm/static/svg/{idwf}.svg`. The `svg_path` property reconstructs the path whenever an endpoint needs to read/write the file. If a file is missing, endpoints return 404 (the editor can regenerate it from BPMN data).

### Schemas (Pydantic v2 / FastAPI models)

Define request/response schemas in `repository_schemas.py`:

- `ModelCreate` — for POST `/api/v1/models` (add endpoint): folder, idwf, name
- `ModelUpdate` — for PUT with data + svg payload
- `ModelDuplicateRequest` — `{ "new_idwf": str }` (alias `"newIdwf"`)
- `SaveAsRequest` — `{ "title": str, "data": dict, "svg": str | None }`
- `FolderUpdate` — `{ "folder": str }`
- `ScriptRequest` — `{ "script": str | None }` (ignored server-side)
- `SaveModelRequest` — `{ "data": dict, "svg": str | None, "title": str | None }`
- `ModelRead` — full model read response (idwf, folder, version, data, created_at, updated_at). **No `svg` field** — SVGs are served as separate file endpoints (`/svg/{idwf}`, `/thumbnail/{idwf}`).
- `SaveResponse` — generic `{ "ok": bool, "msg": str }` used for most mutation responses.

---

### Step 1: PUT `/api/v1/models/save/{idwf}` — `save()`

**Legacy PHP:** `Repository::save()` at line 43–57
```php
$data = json_decode($this->input->post('data'));
$data->properties->modificationdate = date('Y-m-d') . 'T00:00:00';
$svg = $this->input->post('svg');
$idwf = $data->resourceId;
$this->bpm->save($idwf, $data, $svg);
```

**New endpoint:** `PUT /api/v1/models/save/{idwf}` — CodeIgniter convention: function name `save` is the route segment, `{idwf}` from path
- Body: `{ "data": <dict>, "svg": <string> }`
- Sets `properties.modificationdate = now()` in data dict
- Calls service method that upserts model, increments version, writes SVG to disk

**Service logic:**
1. Validate idwf exists or is creatable (auth check)
2. Decode JSON body — extract `data` and `svg`
3. Set `data["properties"]["modificationdate"] = ISO now()`
4. Write `svg` content to `pybpm/static/svg/{idwf}.svg` (create dir if missing)
5. Upsert into `bpm_models`: if exists, bump `version`, update `updated_at`; else create new row
6. Return `ModelRead` with status 200 (update) or 201 (create)

**Tests:**
- PUT existing model → version incremented, modificationdate set
- PUT new model idwf → created with version=1
- PUT without auth → 401
- PUT invalid JSON body → 422
- PUT model with missing `data` field → 400

---

### Step 2: POST `/api/v1/models/duplicate` — `duplicate()`

**Legacy PHP:** lines 59–84
```php
$idwf = $this->input->post('idwf');
$newidwf = $this->input->post('newidwf');
if($exists) { error: already exists }
else { load old, unset _id, set resourceId=newidwf, idwf=newidwf, save_raw }
```

**New endpoint:** `POST /api/v1/models/duplicate` — no URL params (both idwf + new_idwf in POST body)
- Body: `{ "idwf": "<string>", "new_idwf": "<string>" }`
- Returns: `{ "ok": bool, "msg": str }`

**Service logic:**
1. Load source model by `{idwf}` — if not found, return 404
2. Check `model_exists(new_idwf)` — if true, return `{ ok: false, msg: "already exists" }` (HTTP 409)
3. Deep-copy data dict, set `resourceId = new_idwf`, `idwf = new_idwf`
4. Unset any legacy `_id` field
5. Save as raw insert (no version bump, no file I/O — matches `save_raw`)
6. Return `{ ok: true, msg: "created id: $new_idwf" }`

**Tests:**
- Duplicate existing model to new unique id → 201 with success message
- Duplicate to already-existing id → 409 conflict
- Duplicate non-existent source → 404
- Duplicate without auth → 401

---

### Step 3: POST `/api/v1/models/save_as` — `save_as()`

**Legacy PHP:** lines 86–102
```php
$idwf = $this->input->post('title');
$data->resourceId = $idwf;
if(model exists) error 404; else save($idwf, $data, $svg);
```

**New endpoint:** `POST /api/v1/models/save_as` — underscore matches CodeIgniter function name
- Body: `{ "title": "<string>", "data": <dict>, "svg": <string> }`
- Note: legacy uses POST form field `title` (not idwf) as the model identifier

**Service logic:**
1. Extract `title`, `data`, `svg` from body
2. Set `data["resourceId"] = title`
3. Check if model with that id exists — if yes, return 409
4. Call full save (same path as Step 1)

**Tests:**
- Save-as new title → creates model, returns data with resourceId=title
- Save-as existing title → 409 conflict
- Save-as without title field → 422 validation error

---

### Step 4: POST `/api/v1/models/add/{idwf}` — `add($new_idwf=null)` (create scaffold)

**Legacy PHP:** lines 122–171
```php
$idwf = $this->input->post('idwf');
$folder = ...; $name = ...; $user = get_user($idu);
$wf = { idwf, folder, version:0, svg:"", data: { stencilset, resourceId, properties{...}, stencil } };
save_raw($wf);
```

**New endpoint:** `POST /api/v1/models/add/{idwf}` — CodeIgniter convention: `$new_idwf` becomes `{idwf}` path segment (optional; legacy also accepts it from POST body)
- Body: `{ "folder?": "<string>", "name?": "<string>" }` — idwf comes from URL
- Returns: `{ ok: bool, msg: str }` or full model on success

**Service logic:**
1. Validate `idwf` is present (else 400)
2. Check `model_exists(idwf)` — if yes, return 409 "already exists"
3. Build scaffold with defaults matching legacy:
   - `version = 0` (will be bumped to 1 on first save)
    - `folder = post data or "General"`
   - `data.stencilset.url = "../../jscript/bpm-dna2/stencilsets/bpmn2.0/bpmn2.0_2.json"`
   - `data.stencilset.namespace = "http://b3mn.org/stencilset/bpmn2.0#"`
   - `data.resourceId = idwf`
   - `data.properties.name = post name or "New Model"`
   - `data.properties.creationdate = now() as ISO string`
   - `data.properties.modificationdate = ""`
   - `data.stencil.id = "BPMNDiagram"`
4. Insert into DB (raw save, no version bump)

**Tests:**
- Create new model with valid idwf → 201 with scaffold data
- Create with default folder/name when omitted
- Create duplicate idwf → 409
- Create without idwf in body → 400
- Create without auth → 401

---

### Step 5: GET `/api/v1/models/check_model/{name}` — `check_model($name)`

**Legacy PHP:** lines 173–178
```php
$rs = $this->bpm->get_models(array('idwf' => $name));
$result['ok'] = ($rs->count()) ? false : true;
```

**New endpoint:** `GET /api/v1/models/check_model/{name}` — function name preserved, `$name` becomes `{name}` path segment
- Returns: `{ "ok": bool }` — `true` if NOT exists, `false` if model with that id already exists
- Used by the editor's "save as" validation

**Service logic:**
1. Query `bpm_models WHERE idwf = :idwf`
2. Return `{ ok: <not found> }` (boolean inversion of existence)

**Tests:**
- Check non-existent model → `{ ok: true }`
- Check existing model → `{ ok: false }`

---

### Step 6: DELETE `/api/v1/models/delete` — `delete()`

**Legacy PHP:** lines 180–188
```php
$idwf = $this->input->post('idwf');
$result['ok'] = $this->bpm->delete($idwf);
```

**New endpoint:** `DELETE /api/v1/models/delete` — no URL params (legacy reads idwf from POST body)
- Body: `{ "idwf": "<string>" }`
- Returns: `{ "ok": bool, "msg": str }`

**Service logic:**
1. Delete row from `bpm_models WHERE idwf = :idwf`
2. Return appropriate status (204 if deleted, 404 if not found)

**Tests:**
- Delete existing model → 204
- Delete non-existent model → 404
- Delete without auth → 401

---

### Step 7: GET `/api/v1/models/load/{idwf}` — `load($model, $idwf, $mode='', $debug=false)` (primary read endpoint)

**Legacy PHP:** lines 190–223
```php
$idwf = urldecode($idwf);
$mywf = $this->bpm->load($idwf, false);
$template = { resourceId, stencilset, stencil } // fallback if data missing
$data = ($mywf['data']) ? $mywf['data'] : $template;
// Returns JSON with Cache-Control: no-store headers
```

**New endpoint:** `GET /api/v1/models/load/{idwf}` — CodeIgniter convention: function name `load` is the route segment, `{idwf}` from path. Optional `$mode` and `$debug` passed as query params (FastAPI can't represent optional trailing path segments).
- Query params: `?mode=` (optional), `?debug=` (bool) for verbose output
- Returns: JSON model data (`data` sub-tree only, matching legacy behavior)
- Headers: `Cache-Control: no-store, no-cache, must-revalidate`

**Service logic:**
1. URL-decode the idwf path param
2. Load from DB — if not found, return 404
3. If `data` is null/empty, use template fallback (stencilset + stencil)
4. Return data dict as JSON response with no-cache headers

**Tests:**
- Load existing model → returns data dict
- Load non-existent model → 404
- Model with empty data → falls back to template
- No auth → 401

---

### Step 8: GET `/api/v1/models/dump/{idwf}` — `dump($model, $idwf, $expand=false)`

**Legacy PHP:** lines 236–251
```php
$mywf = $this->bpm->load($idwf, $expand); // expand=true by default for full tree
// Returns { htmltitle, theme, base_url, idwf, data } as JSON
```

**New endpoint:** `GET /api/v1/models/dump/{idwf}` — function name `dump` is route segment, `{idwf}` from path. `$expand` as query param.
- Query param: `?expand=false` (default false) — when true, recursively resolve sub-processes

**Service logic:**
1. Load model with optional expand flag (same as load but toggles recursive resolution)
2. Return full object `{ idwf, data }` plus metadata (`htmltitle`, `theme`, `base_url`)

**Tests:**
- Dump with expand=false → shallow model data
- Dump with expand=true → recursively resolved sub-processes
- Dump non-existent → 404

---

### Step 9: POST `/api/v1/models/save_script/{idwf}/{resource_id}` — `save_script($idwf, $resourceId)` *(stub)*

**Legacy PHP:** lines 288–313
```php
$mywf = $this->bpm->load($idwf);
$wf = $mywf['data'];
$this->bpm->save($idwf, $wf, $mywf['svg']); // full save with current data+svg
echo "Saved!";
```

**New endpoint:** `POST /api/v1/models/save_script/{idwf}/{resource_id}` — function name preserved as route segment
- Body: `{ "script": "<string>" }` — the script content to set on a shape (ignored server-side)
- Note: legacy actually just re-saves the existing model. The `script` field is ignored; this endpoint currently returns a no-op success response matching the stub pattern.

**Service logic:** Stub — returns `SaveResponse(ok=True, msg="script saved (no-op)")`. To implement fully: load model, re-save via full save path with version bump and modificationdate.

**Tests:**
- Save script on existing model → 200 with success message (stub)
- Save script on non-existent model → stub returns success regardless of existence

---

### Step 10: POST `/api/v1/models/save_model/{idwf}` — `save_model($idwf)`

**Legacy PHP:** lines 314–333
```php
$data = json_decode($this->input->post('data'));
$mywf = $this->bpm->load($idwf);
$this->bpm->save($idwf, $data, $mywf['svg']); // save with current SVG
echo "Saved!";
```

**New endpoint:** `POST /api/v1/models/save_model/{idwf}` — CodeIgniter convention: function name + `{idwf}` path segment
- Body: `{ "data": <dict>, "svg": <string>, "title?": <string> }`

**Service logic:**
1. Extract idwf from `body.data["resourceId"]` — 400 if missing
2. Call full save (version bump, modificationdate) and write SVG to disk
3. Return success message

**Tests:**
- Save updated data on existing model → version bumped, returns "Saved!"
- Save with missing resourceId in body → 400
- Save without auth → 401

---

### Step 11: GET `/api/v1/models/thumbnail/{idwf}/{width}/{height}` — `thumbnail($idwf, $width, $heigth)` *(stub)*

**Legacy PHP:** lines 334–345
```php
$svg = $this->bpm->svg($idwf);
header("Content-type: image/svg+xml");
echo $svg; // raw SVG, no wrapper tags added
```

**New endpoint:** `GET /api/v1/models/thumbnail/{idwf}/{width}/{height}` — all three params as path segments (matches CodeIgniter convention)
- Returns: **raw SVG content** with `Content-Type: image/svg+xml` header
- **Implementation note**: Thumbnail generation (SVG → PNG) is deferred. This endpoint currently returns the raw SVG file from disk as a placeholder. When phantomjs/cairosvg support is added later, swap in proper thumbnail generation here.

**Service logic:**
1. Load model — 404 if not found
2. Check that `pybpm/static/svg/{idwf}.svg` exists on disk — 404 if missing
3. Return raw SVG file content with `Content-Type: image/svg+xml`

---

### Step 12: GET `/api/v1/models/svg/{idwf}` — `svg($idwf)`

**Legacy PHP:** lines 347–361
```php
$mywf = $this->bpm->load($idwf, false);
$data['svg'] = str_replace('>', ">\n", $mywf['svg']); // add newlines after >
// Returns XML with <?xml version="1.0" encoding="utf-8"?> header
```

**New endpoint:** `GET /api/v1/models/svg/{idwf}` — function name preserved as route segment
- Returns: **formatted SVG string** from file on disk, with XML declaration header and `Content-Type: image/svg+xml`

**Service logic:**
1. Load model — 404 if not found
2. Read SVG file at `pybpm/static/svg/{idwf}.svg` — 404 if missing
3. Optionally format (add newlines after `>` to match legacy behavior)
4. Prepend XML declaration `<?xml version="1.0" encoding="utf-8"?>`
5. Return with `Content-Type: image/svg+xml`

**Tests:**
- SVG for existing model → returns SVG string with xml declaration header
- SVG non-existent model → 404

---

### Step 13: GET `/api/v1/models/get_shapes/{idwf}/{debug}` — `get_shapes($model, $idwf, $debug=false)`

**Legacy PHP:** lines 363–380
```php
$mywf = $this->bpm->load($idwf, true); // expand=true
$wf = bindArrayToObject($mywf['data']);
$shapes = $this->bpm->get_all_shapes($wf);
foreach ($shapes as $shape) {
    $data['shapes'][$shape->resourceId] = $shape;
}
```

**New endpoint:** `GET /api/v1/models/get_shapes/{idwf}/{debug}` — function name preserved, `{debug}` path segment (optional via query param fallback)
- Query param: `?debug=` (bool, default false, verbose output)
- Returns: `{ "idwf": "<string>", "shapes": { "<resource_id>": <shape_dict>, ... } }` — shapes indexed by resourceId

**Service logic:**
1. Load model with expand=true (resolve sub-processes for complete shape tree)
2. Recursively walk `data.childShapes` to collect all shapes into dict keyed by `resourceId`
3. Return `{ idwf, shapes: {...} }` as JSON

**Tests:**
- Shapes for model → returns shapes dict indexed by resourceId
- Empty model → empty shapes dict
- Model with nested sub-processes (expand=true) → recursively includes all child shapes

---

### Step 14: GET `/api/v1/models/get_comments/{idwf}/{resource_id}` — `get_comments($model, $idwf, $resourceId)`

**Legacy PHP:** lines 492–505
```php
$mywf = $this->bpm->load($idwf, false);
$wf = $this->bpm->bindArrayToObject($mywf['data']);
$shape = $this->bpm->get_shape($resourceId, $wf);
echo $shape->stencil->id . '<br/>';
echo $shape->properties->documentation;
```

**New endpoint:** `GET /api/v1/models/get_comments/{idwf}/{resource_id}` — function name preserved as route segment
- Returns: `{ "stencil_id": "<string>", "documentation": "<string>" }`

**Service logic:**
1. Load model, find shape by resourceId (walk childShapes recursively)
2. Return shape's `stencil.id` and `properties.documentation`
3. 404 if shape not found

**Tests:**
- Get comments for shape with documentation → returns stencil_id + documentation
- Get comments for shape without documentation → empty string
- Get comments for non-existent resourceId → 404

---

### Step 15: POST `/api/v1/models/import` — `Import($model)` (zip upload)

**Legacy PHP:** lines 513–603
```php
// Handles zip file upload, extracts to disk, reads model.json + svg.svg from archive,
// then saves via save_raw() or save() depending on whether model already exists.
$config['allowed_types'] = 'zip';
$zip->extractTo(APPPATH."modules/bpm/assets/files/");
$idwf = str_replace('.zip','',$upload_data['client_name']);
$filename = $path."model/$idwf.json";
$svg_filename = $path."svg/$idwf.svg";
$data = json_decode(read_file($filename), false);
if(model_exists) { save(); } else { save_raw(); }
```

**New endpoint:** `POST /api/v1/models/import` — no URL params (legacy `$model` param is implicit, not used in function body)
- Form field: `file` — a `.zip` archive containing `{model_name}.json` and `{model_name}.svg`
- Returns: `{ "ok": bool, "msg": "<string>" }`

**Service logic:**
1. Accept multipart file with `python-multipart`
2. Validate file extension is `.zip` — else return 400/415
3. Extract zip to temp directory (use `tempfile.TemporaryDirectory()`)
4. Derive idwf from filename: `Path(zip_name).stem` (strip `.zip`)
5. Look for `{idwf}.json` and `{idwf}.svg` in extracted contents
6. Copy SVG file from extract to `pybpm/static/svg/{idwf}.svg`
7. If model already exists → call full save; else → save_raw insert with folder="General"
8. Clean up temp directory

**Tests:**
- Import valid zip with json+svg → creates or updates model, returns ok=true; SVG file written to disk
- Import zip missing json file → error response
- Import non-zip file → 400/415 unsupported media type
- Import duplicate (model exists) → updates existing model via save()

---

### Step 16: POST `/api/v1/models/update_folder` — `update_folder()`

**Legacy PHP:** lines 622–637
```php
$idwf = $this->input->post('idwf');
$folder = strip_tags_content($this->input->post('folder'));
$this->bpm->update_folder($idwf, $folder);
```

**New endpoint:** `POST /api/v1/models/update_folder` — no URL params (legacy reads idwf + folder from POST body)
- Body: `{ "idwf": "<string>", "folder": "<string>" }` (strip HTML tags client-side or server-side)
- Returns: `{ ok: bool, msg: str }` or updated model

**Service logic:**
1. Strip any HTML tags from folder value (sanitization)
2. Update `bpm_models.folder` field where idwf matches
3. Return updated folder value

**Tests:**
- Update folder for existing model → returns new folder value, 200
- Update folder with HTML in name → sanitized before write
- Update non-existent model → 404

---

## Auth Integration

All endpoints require JWT bearer token authentication. Create a FastAPI dependency:

```python
# auth.py (FastAPI-style)
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from config import Config

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(
            credentials.credentials,
            Config.SECRET_KEY,
            algorithms=["HS256"]
        )
        user_id = int(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user_id
```

Apply `Depends(get_current_user)` to all repository endpoints. The legacy PHP does `$this->user->authorize()` in the constructor — replicate by applying a dependency or middleware to the router prefix `/api/v1/models`.

---

## File: Directory Structure

Key files for the repository endpoints:

```
pybpm/
├── static/
│   └── svg/               # SVG files live here: {idwf}.svg (auto-created at startup)
├── app/
│   ├── api/
│   │   └── bpm.py         # FastAPI router with all 15+ repository endpoints
│   ├── models/
│   │   └── bpm_model.py   # BpmModel SQLAlchemy class (with svg_path property)
│   ├── schemas/
│   │   └── repository.py  # Pydantic request/response schemas
│   └── services/
│       └── model_service.py  # Business logic for model CRUD
├── tests/
│   ├── conftest.py        # existing async test fixtures
│   └── test_repository.py # integration tests for all endpoints (NEW)
```

**Startup hook**: On FastAPI app startup, create `pybpm/static/svg/` if it does not exist:

```python
@app.on_event("startup")
async def ensure_svg_dir():
    SVG_DIR.mkdir(parents=True, exist_ok=True)
```

---

## Test Plan Summary

Single layer of integration tests only — no service-layer unit tests. All tests use httpx AsyncClient against a real test database and test DB endpoints directly.

Each endpoint gets these categories of tests:

| Category | What it covers |
|----------|---------------|
| **Happy path** | Valid request returns expected status + correct response body; SVG file written to disk where applicable |
| **Auth** | Missing/invalid JWT → 401; valid JWT proceeds normally |
| **Validation** | Missing required fields → 422 (Pydantic); wrong types → 422 |
| **Business logic** | Duplicate idwf → 409; non-existent model → 404; version bumping works correctly |
| **Edge cases** | Empty data dict uses template fallback; HTML in folder gets sanitized; URL-encoded idwf is decoded; SVG file missing on disk → 404 |

Target: **~55 test functions total** across the 17 endpoints (average ~3 per endpoint).

Run tests with: `uv run pytest`

---

## Migration Notes

After implementing the model and schemas, generate an Alembic migration if needed:

```bash
cd pybpm && uv run alembic revision --autogenerate -m "Add BpmModel table for repository"
uv run alembic upgrade head
```

The `bpm_models` table already exists in the initial schema — verify column types match. **Important**: The legacy migration includes an `svg TEXT` column that should be dropped since SVGs now live on disk at `pybpm/static/svg/{idwf}.svg`. Add a migration to remove it:

```bash
cd pybpm && uv run alembic revision -m "Drop svg column from bpm_models (SVGs stored as files)"
```

If the JSONB column needs a type adjustment (SQLite uses TEXT vs PostgreSQL uses JSONB), ensure SQLAlchemy's `db.JSON` maps correctly to both dialects.

---

## Running & Troubleshooting

### Start the Dev Server

```bash
# From pybpm/ directory:
uv sync                                    # install dependencies
docker compose up -d db                    # start PostgreSQL container
uv run uvicorn main:app --reload           # hot-reload dev server on http://localhost:8000
```

Verify OpenAPI docs at `http://localhost:8000/docs` — all 17 endpoints should appear under the **models** tag.

### Common Errors & Fixes

#### 1. `ModuleNotFoundError: No module named 'app'`
**Cause:** Running uvicorn from wrong directory or missing `pybpm/` in Python path.  
**Fix:** Always run from inside `pybpm/`:
```bash
cd pybpm && uv run uvicorn main:app --reload
```

#### 2. `ImportError: cannot import name 'X' from 'app.api.bpm'`
**Cause:** Circular imports between routers, models, and services.  
**Fix:** 
- Keep models in `app/models/`, schemas in `app/schemas/`, services in `app/services/`, routers in `app/api/`.
- Routers should only import from services (not other routers).
- Services import models + schemas.
- If you hit a circular import, move the shared type to `app/types.py` or use string annotations (`from __future__ import annotations`).

#### 3. `sqlalchemy.exc.OperationalError: could not connect to server`
**Cause:** PostgreSQL container not running or wrong credentials in `.env`.  
**Fix:**
```bash
docker compose up -d db                    # ensure DB is up
uv run alembic upgrade head                # apply pending migrations
```

#### 4. `pydantic.error_wrappers.ValidationError: X validation error`
**Cause:** Request body doesn't match the Pydantic schema (wrong field names, missing required fields).  
**Fix:** Check the request against the schema in `app/schemas/repository.py`. The OpenAPI docs at `/docs` show exact field requirements. Common issues:
- Using `newIdwf` instead of `new_idwf` for `ModelDuplicateRequest` (alias defined in schema)
- Sending `svg` as base64 string when the endpoint expects raw SVG text

#### 5. Route conflicts — `HTTPException: Multiple handlers match path`
**Cause:** Two routes match the same URL pattern. Common culprits:
- Static route `/save` vs dynamic `/{idwf}` for POST requests
- Missing function name prefix (e.g., `GET /{idwf}` instead of `GET /load/{idwf}`)

**Fix:** Every route must include the function name as the first segment:
```python
# WRONG — too generic, conflicts with other routes
@router.get("/{idwf}")

# CORRECT — matches CodeIgniter convention
@router.get("/load/{idwf}")
```

#### 6. `AttributeError: 'BpmModel' object has no attribute 'svg'`
**Cause:** Legacy code expected an `svg` column on the model, but it was dropped (SVGs now live in `static/svg/`).  
**Fix:** Use `model.svg_path` property instead of `model.svg`. The property reconstructs the path from `{idwf}.svg`.

#### 7. SVG file not found — `404 Not Found` on `/svg/{idwf}`
**Cause:** SVG file doesn't exist at `pybpm/static/svg/{idwf}.svg`.  
**Fix:** Ensure the SVG was written during save:
```python
# In service.save(): 
svg_dir = Path(__file__).parent.parent / "static" / "svg"
svg_dir.mkdir(parents=True, exist_ok=True)
(svg_dir / f"{idwf}.svg").write_text(svg_content, encoding="utf-8")
```

#### 8. Alembic migration fails — `multiple primary keys` or column mismatch
**Cause:** Schema drift between SQLAlchemy models and DB state.  
**Fix:**
```bash
cd pybpm && uv run alembic downgrade base    # reset (dev only!)
uv run alembic upgrade head                   # re-apply from scratch
```

### Testing

```bash
# Run all tests:
uv run pytest

# Run just repository tests:
uv run pytest tests/test_repository.py -v

# Run with coverage:
uv run pytest --cov=app.api --cov=app.services tests/

# Single test:
uv run pytest tests/test_repository.py::test_save_existing_model -v
```

### Debugging Tips

1. **Check route registration:** `http://localhost:8000/openapi.json | jq '.paths | keys'` — all 17 routes should appear.
2. **Test a single endpoint with curl:**
   ```bash
   curl -X PUT http://localhost:8000/api/v1/models/save/test_model \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"data": {"resourceId": "test_model"}, "svg": "<svg/>"}'
   ```
3. **Verify DB state:** `docker compose exec db psql -U bpmuser -d bpddb -c "SELECT idwf, version FROM bpm_models;"`
4. **Check SVG file:** `ls -la pybpm/static/svg/`
