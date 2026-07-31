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
| Project layout | Flat module style (matching existing pybpm): top-level `repository.py`, models at top level, no nested `app/` structure until explicitly reorganized |

---

## Progress Tracker

<!-- Agents: check off [x] each item as it's completed. Pick up where the last unchecked box is. -->

### 0. Scaffolding & Infrastructure
- [ ] Add `python-multipart` dependency to pyproject.toml (for multipart form uploads)
- [ ] Create `pybpm/static/svg/` directory (auto-created at startup if missing)
- [ ] Add Alembic migration to drop `svg TEXT` column from `bpm_models` table
- [ ] Update existing conftest.py / test fixtures for repository tests

### 1. Data Layer
- [ ] Create `pybpm/models/bpm_model.py` with `BpmModel` SQLAlchemy class (no `svg` column, `svg_path` property)
- [ ] Create `pybpm/repository_schemas.py` with Pydantic request/response models:
  - `ModelCreate`, `ModelUpdate`, `ModelDuplicateRequest`, `SaveAsRequest`, `FolderUpdate`
  - `ImportResponse`, `ModelRead` (no svg field in read response)

### 2. Auth Dependency
- [ ] Create FastAPI JWT bearer dependency (`get_current_user`) using `python-jose`

### 3. Core Endpoints (CRUD)
- [ ] Step 1: PUT `/api/v1/models/{idwf}` — save/update model + write SVG to disk
- [ ] Step 2: POST `/api/v1/models/{idwf}/duplicate` — clone to new idwf
- [ ] Step 3: POST `/api/v1/models/save-as` — save as new model with custom title
- [ ] Step 4: POST `/api/v1/models` — create brand-new empty scaffold

### 4. Read / Query Endpoints
- [ ] Step 5: GET `/api/v1/models/check/{idwf}` — check existence (for editor validation)
- [ ] Step 6: DELETE `/api/v1/models/{idwf}` — delete model by idwf
- [ ] Step 7: GET `/api/v1/models/{idwf}` — load full model data (primary read, template fallback)
- [ ] Step 8: GET `/api/v1/models/{idwf}/dump` — debug dump with expand flag

### 5. Save Variant Endpoints
- [ ] Step 9: POST `/api/v1/models/{idwf}/script` — save script (re-save full model state)
- [ ] Step 10: POST `/api/v1/models/{idwf}/save` — save data payload with current SVG from disk

### 6. SVG / Visual Endpoints
- [ ] Step 11: GET `/api/v1/models/{idwf}/thumbnail` — stub (returns raw SVG, thumbnail gen deferred)
- [ ] Step 12: GET `/api/v1/models/{idwf}/svg` — return formatted SVG from file on disk

### 7. Shape / Comment Endpoints
- [ ] Step 13: GET `/api/v1/models/{idwf}/shapes` — get all diagram shapes indexed by resourceId
- [ ] Step 14: GET `/api/v1/models/{idwf}/comments/{resource_id}` — get shape documentation/comments

### 8. Import / Bulk Operations
- [ ] Step 15: POST `/api/v1/models/import` — upload + import `.zip` model archive (multipart)

### 9. Folder Management
- [ ] Step 16: PATCH `/api/v1/models/{idwf}/folder` — move model into different folder (HTML tag sanitization)

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

| # | PHP Method | HTTP Verb + Path (Legacy) | RESTful Equivalent (New) | Description |
|---|-----------|--------------------------|-------------------------|-------------|
| 1 | `save()` | POST `/repository/save` | **POST** `/api/v1/models/{idwf}` | Update model data + SVG (full save with version bump, modification date) |
| 2 | `duplicate()` | POST `/repository/duplicate` | **POST** `/api/v1/models/{idwf}/duplicate` | Clone a model to a new idwf |
| 3 | `save_as()` | POST `/repository/save_as` | **POST** `/api/v1/models/save-as` | Save as new model with custom title/idwf |
| 4 | `add()` | POST `/repository/add` | **POST** `/api/v1/models` | Create a brand-new empty model scaffold |
| 5 | `check_model()` | GET `/repository/check_model/{name}` | **GET** `/api/v1/models/check/{idwf}` | Check if a model id already exists (validator for editor) |
| 6 | `delete()` | POST `/repository/delete` | **DELETE** `/api/v1/models/{idwf}` | Delete a model by idwf |
| 7 | `load()` | GET `/repository/load/{model}/{idwf}` | **GET** `/api/v1/models/{idwf}` | Load full model data (JSON) for editor |
| 8 | `edit()` | GET `/repository/edit/{model}/{idwf}` | *(removed — served by frontend SPA)* | Returns XHTML page, not an API endpoint. Frontend serves this directly. |
| 9 | `dump()` | GET `/repository/dump/{model}/{idwf}` | **GET** `/api/v1/models/{idwf}/dump` | Debug dump of model with expand flag (all sub-processes resolved) |
| 10 | `json_view()` | GET `/repository/json_view/{model}/{idwf}` | *(removed — frontend view)* | Renders a JS-powered JSON editor page. Not an API endpoint. |
| 11 | `save_script()` | POST `/repository/save_script/{idwf}/{resourceId}` | **POST** `/api/v1/models/{idwf}/script` | Save script content on a specific shape/resourceId (full save) |
| 12 | `save_model()` | POST `/repository/save_model/{idwf}` | **POST** `/api/v1/models/{idwf}/save` | Save model data payload with current SVG (alias of full save) |
| 13 | `thumbnail()` | GET `/repository/thumbnail/{idwf}/{width}/{height}` | **GET** `/api/v1/models/{idwf}/thumbnail` | Return raw SVG for thumbnail rendering |
| 14 | `svg()` | GET `/repository/svg/{model}/{idwf}` | **GET** `/api/v1/models/{idwf}/svg` | Return SVG content with XML headers |
| 15 | `get_shapes()` | GET `/repository/get_shapes/{model}/{idwf}` | **GET** `/api/v1/models/{idwf}/shapes` | Get all diagram shapes indexed by resourceId (for editor interaction) |
| 16 | `view()` | GET `/repository/view/{model}/{idwf}` | *(removed — frontend view)* | Renders the model viewer page. Not an API endpoint. |
| 17 | `tokens()` | GET `/repository/tokens/{model}/{idwf}/{idcase}` | **GET** `/api/v1/cases/{idwf}/{case_id}/tokens` | Get process tokens for a case instance (moved to Case Manager scope) |
| 18 | `get_comments()` | GET `/repository/get_comments/{model}/{idwf}/{resourceId}` | **GET** `/api/v1/models/{idwf}/comments/{resource_id}` | Get documentation/comments for a shape |
| 19 | `upload()` | GET/POST `/repository/upload` | *(removed — UI form)* | Shows upload HTML form. Frontend handles file picking. |
| 20 | `Import()` | POST `/repository/import` | **POST** `/api/v1/models/import` | Upload and import a `.zip` model archive (drop-in replacement) |
| 21 | `import_test()` | GET `/repository/import_test` | *(removed — dev only)* | Dev-only batch import of test models. Not shipped to production. |
| 22 | `update_folder()` | POST `/repository/update_folder` | **PATCH** `/api/v1/models/{idwf}/folder` | Move a model into a different folder |
| 23 | `repair_stencil_path()` | GET (dev-only) | *(removed — one-time migration)* | Fixes broken stencilset URLs. Not an API endpoint. |

### Summary: 15 actionable endpoints to implement

The table above removes UI-only endpoints (`edit`, `json_view`, `view`, `upload`, `import_test`) and dev-migration endpoints (`repair_stencil_path`). The remaining **15 RESTful endpoints** are listed below with implementation steps.

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
- `ModelUpdate` — for POST/PUT with data + svg payload
- `ModelDuplicateRequest` — `{ "idwf": str, "new_idwf": str }`
- `SaveAsRequest` — `{ "title": str, "data": dict, "svg": str }`
- `FolderUpdate` — `{ "folder": str }`
- `ImportResponse` — `{ "ok": bool, "msg": str }`
- `ModelRead` — full model read response (idwf, folder, version, data, created_at, updated_at). **No `svg` field** — SVGs are served as separate file endpoints (`/svg/{idwf}`, `/thumbnail/{idwf}`).

---

### Step 1: POST `/api/v1/models/{idwf}` — `save()` → RESTful save/update

**Legacy PHP:** `Repository::save()` at line 43–57
```php
$data = json_decode($this->input->post('data'));
$data->properties->modificationdate = date('Y-m-d') . 'T00:00:00';
$svg = $this->input->post('svg');
$idwf = $data->resourceId;
$this->bpm->save($idwf, $data, $svg);
```

**New endpoint:** `PUT /api/v1/models/{idwf}` (or POST — the legacy uses POST but RESTful convention is PUT for full replacement)
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

### Step 2: POST `/api/v1/models/{idwf}/duplicate` — `duplicate()`

**Legacy PHP:** lines 59–84
```php
$idwf = $this->input->post('idwf');
$newidwf = $this->input->post('newidwf');
if($exists) { error: already exists }
else { load old, unset _id, set resourceId=newidwf, idwf=newidwf, save_raw }
```

**New endpoint:** `POST /api/v1/models/{idwf}/duplicate`
- Body: `{ "new_idwf": "<string>" }` (path param provides source idwf)
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

### Step 3: POST `/api/v1/models/save-as` — `save_as()`

**Legacy PHP:** lines 86–102
```php
$idwf = $this->input->post('title');
$data->resourceId = $idwf;
if(model exists) error 404; else save($idwf, $data, $svg);
```

**New endpoint:** `POST /api/v1/models/save-as`
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

### Step 4: POST `/api/v1/models` — `add()` (create scaffold)

**Legacy PHP:** lines 122–171
```php
$idwf = $this->input->post('idwf');
$folder = ...; $name = ...; $user = get_user($idu);
$wf = { idwf, folder, version:0, svg:"", data: { stencilset, resourceId, properties{...}, stencil } };
save_raw($wf);
```

**New endpoint:** `POST /api/v1/models` (no path param)
- Body: `{ "idwf": "<string>", "folder?": "<string>", "name?": "<string>" }`
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

### Step 5: GET `/api/v1/models/check/{idwf}` — `check_model()`

**Legacy PHP:** lines 173–178
```php
$rs = $this->bpm->get_models(array('idwf' => $name));
$result['ok'] = ($rs->count()) ? false : true;
```

**New endpoint:** `GET /api/v1/models/check/{idwf}`
- Returns: `{ "ok": bool }` — `true` if NOT exists, `false` if model with that id already exists
- Used by the editor's "save as" validation

**Service logic:**
1. Query `bpm_models WHERE idwf = :idwf`
2. Return `{ ok: <not found> }` (boolean inversion of existence)

**Tests:**
- Check non-existent model → `{ ok: true }`
- Check existing model → `{ ok: false }`

---

### Step 6: DELETE `/api/v1/models/{idwf}` — `delete()`

**Legacy PHP:** lines 180–188
```php
$idwf = $this->input->post('idwf');
$result['ok'] = $this->bpm->delete($idwf);
```

**New endpoint:** `DELETE /api/v1/models/{idwf}` (path param, matches RESTful convention)
- Returns: `{ "ok": bool }` or 204 No Content on success

**Service logic:**
1. Delete row from `bpm_models WHERE idwf = :idwf`
2. Return appropriate status (204 if deleted, 404 if not found)

**Tests:**
- Delete existing model → 204
- Delete non-existent model → 404
- Delete without auth → 401

---

### Step 7: GET `/api/v1/models/{idwf}` — `load()` (primary read endpoint)

**Legacy PHP:** lines 190–223
```php
$idwf = urldecode($idwf);
$mywf = $this->bpm->load($idwf, false);
$template = { resourceId, stencilset, stencil } // fallback if data missing
$data = ($mywf['data']) ? $mywf['data'] : $template;
// Returns JSON with Cache-Control: no-store headers
```

**New endpoint:** `GET /api/v1/models/{idwf}` (note: same path as Step 4's POST, but different HTTP verb — FastAPI handles this)
- Query param: `?debug=true` for verbose output (optional, not in RESTful spec)
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

### Step 8: GET `/api/v1/models/{idwf}/dump` — `dump()`

**Legacy PHP:** lines 236–251
```php
$mywf = $this->bpm->load($idwf, $expand); // expand=true by default for full tree
// Returns { htmltitle, theme, base_url, idwf, data } as JSON
```

**New endpoint:** `GET /api/v1/models/{idwf}/dump`
- Query param: `?expand=false` (default false) — when true, recursively resolve sub-processes

**Service logic:**
1. Load model with optional expand flag (same as load but toggles recursive resolution)
2. Return full object `{ idwf, data }` plus metadata (`htmltitle`, `theme`, `base_url`)

**Tests:**
- Dump with expand=false → shallow model data
- Dump with expand=true → recursively resolved sub-processes
- Dump non-existent → 404

---

### Step 9: POST `/api/v1/models/{idwf}/script` — `save_script()`

**Legacy PHP:** lines 288–313
```php
$mywf = $this->bpm->load($idwf);
$wf = $mywf['data'];
$this->bpm->save($idwf, $wf, $mywf['svg']); // full save with current data+svg
echo "Saved!";
```

**New endpoint:** `POST /api/v1/models/{idwf}/script`
- Body: `{ "script": "<string>" }` — the script content to set on a shape
- Note: legacy actually just re-saves the existing model (does not modify data with new script inline). The `script` post field is ignored in practice; this is effectively a "save current state" call.

**Service logic:**
1. Load model by `{idwf}` — 404 if missing (or SVG file missing)
2. Re-save using full save path (version bump, modificationdate)
3. Return success message

**Tests:**
- Save script on existing model → 200 with "Saved!" confirmation
- Save script on non-existent model → 404

---

### Step 10: POST `/api/v1/models/{idwf}/save` — `save_model()`

**Legacy PHP:** lines 314–333
```php
$data = json_decode($this->input->post('data'));
$mywf = $this->bpm->load($idwf);
$this->bpm->save($idwf, $data, $mywf['svg']); // save with current SVG
echo "Saved!";
```

**New endpoint:** `POST /api/v1/models/{idwf}/save`
- Body: `{ "data": <dict> }` — new data payload (SVG kept from existing file on disk)

**Service logic:**
1. Load existing model and verify SVG file exists at `pybpm/static/svg/{idwf}.svg` — 404 if missing
2. Full save with new `data`, keeping old SVG file unchanged
3. Return success message

**Tests:**
- Save updated data on existing model → version bumped, returns "Saved!"
- Save on non-existent model → 404
- Save without auth → 401

---

### Step 11: GET `/api/v1/models/{idwf}/thumbnail` — `thumbnail()` *(stub)*

**Legacy PHP:** lines 334–345
```php
$svg = $this->bpm->svg($idwf);
header("Content-type: image/svg+xml");
echo $svg; // raw SVG, no wrapper tags added
```

**New endpoint:** `GET /api/v1/models/{idwf}/thumbnail`
- Query params (legacy passes via URL but ignored in code): `{width}`, `{height}` — for future thumbnail generation
- Returns: **raw SVG content** with `Content-Type: image/svg+xml` header
- **Implementation note**: Thumbnail generation (SVG → PNG) is deferred. This endpoint currently returns the raw SVG file from disk as a placeholder. When phantomjs/cairosvg support is added later, swap in proper thumbnail generation here.

**Service logic:**
1. Load model — 404 if not found
2. Check that `pybpm/static/svg/{idwf}.svg` exists on disk — 404 if missing
3. Return raw SVG file content with `Content-Type: image/svg+xml`

---

### Step 12: GET `/api/v1/models/{idwf}/svg` — `svg()`

**Legacy PHP:** lines 347–361
```php
$mywf = $this->bpm->load($idwf, false);
$data['svg'] = str_replace('>', ">\n", $mywf['svg']); // add newlines after >
// Returns XML with <?xml version="1.0" encoding="utf-8"?> header
```

**New endpoint:** `GET /api/v1/models/{idwf}/svg`
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

### Step 13: GET `/api/v1/models/{idwf}/shapes` — `get_shapes()`

**Legacy PHP:** lines 363–380
```php
$mywf = $this->bpm->load($idwf, true); // expand=true
$wf = bindArrayToObject($mywf['data']);
$shapes = $this->bpm->get_all_shapes($wf);
foreach ($shapes as $shape) {
    $data['shapes'][$shape->resourceId] = $shape;
}
```

**New endpoint:** `GET /api/v1/models/{idwf}/shapes`
- Query param: `?debug=true` (optional, verbose output)
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

### Step 14: GET `/api/v1/models/{idwf}/comments/{resource_id}` — `get_comments()`

**Legacy PHP:** lines 492–505
```php
$mywf = $this->bpm->load($idwf, false);
$wf = $this->bpm->bindArrayToObject($mywf['data']);
$shape = $this->bpm->get_shape($resourceId, $wf);
echo $shape->stencil->id . '<br/>';
echo $shape->properties->documentation;
```

**New endpoint:** `GET /api/v1/models/{idwf}/comments/{resource_id}`
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

### Step 15: POST `/api/v1/models/import` — `Import()` (zip upload)

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

**New endpoint:** `POST /api/v1/models/import` (multipart form upload)
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

### Step 16: PATCH `/api/v1/models/{idwf}/folder` — `update_folder()`

**Legacy PHP:** lines 622–637
```php
$idwf = $this->input->post('idwf');
$folder = strip_tags_content($this->input->post('folder'));
$this->bpm->update_folder($idwf, $folder);
```

**New endpoint:** `PATCH /api/v1/models/{idwf}/folder`
- Body: `{ "folder": "<string>" }` (strip HTML tags client-side or server-side)
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

Create these files under pybpm/:

```
pybpm/
├── static/
│   └── svg/               # SVG files live here: {idwf}.svg (auto-created at startup)
├── models/
│   ├── __init__.py        # re-exports all models for migrations
│   └── bpm_model.py       # BpmModel SQLAlchemy class (new, with svg_path property)
├── repository.py          # FastAPI router with all 15+ endpoints (NEW)
├── repository_schemas.py  # Pydantic request/response schemas (NEW)
└── tests/
    ├── conftest.py        # existing async test fixtures
    └── test_repository.py # integration tests for all endpoints (NEW)
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

Target: **~50 test functions total** across the 16 endpoints (average ~3 per endpoint).

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
