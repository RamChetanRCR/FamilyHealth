# Family Health — Project Dump

Everything about this repository in one file. Quick-start lives in `README.md`.

**Status:** private family health records — working MVP for local/server use.
**Not production-ready:** no authentication/authorization yet (see §Security).

---

## 1. What it does

- Family member profiles (name, dob, gender)
- Prescription upload (JPEG/PNG/PDF) tied to a specific member
- OCR of uploaded images (Tesseract), raw text stored, manually correctable
- Original document stored with a generated filename, viewable in the UI
- Structured prescription records: date, doctor, hospital, diagnosis, medicines
- Home medicine inventory (separate from prescriptions — intentionally)
- Print-for-doctor view (browser print → PDF)
- Search within a member's prescriptions

Deliberately **not** built yet: React/any frontend framework, auth, chatbot,
MCP, structured extraction, PDF text extraction, inventory photos.

## 2. Stack

| Layer | Choice |
|---|---|
| Language | Python 3.13 (`.python-version`; spec said 3.12 — 3.13 kept deliberately) |
| API | FastAPI + Uvicorn |
| DB | PostgreSQL 17 (Docker) / any local Postgres or SQLite (tests) |
| ORM | SQLAlchemy 2.0 (typed `Mapped` models) |
| OCR | Tesseract 5.x via pytesseract + Pillow |
| Frontend | Single static HTML file, vanilla JS + CSS. **No framework, no build step** |
| Frontend server | `frontend/server.py` — Python stdlib http.server: serves UI + reverse-proxies API. No nginx (explicit requirement) |
| Deps | `pyproject.toml` is the single source (no requirements.txt) |
| Tests | pytest + FastAPI TestClient (httpx2) |

## 3. Repository layout

```
backend/
  app/
    main.py          # FastAPI app: routes, schemas, upload pipeline
    models.py        # SQLAlchemy models (4 tables)
    database.py      # engine + SessionLocal (DATABASE_URL env)
    storage.py       # save_document() → STORAGE_DIR, uuid filename
    ocr.py           # extract_text(): preprocess + tesseract
    init_db.py       # create_all script (run by container CMD)
  Dockerfile         # python:3.13-slim + tesseract-ocr, pip install .
frontend/
  index.html         # the entire UI (HTML+CSS+JS)
  server.py          # stdlib static server + API proxy (API_URL/HOST/PORT env)
  Dockerfile         # python:3.13-slim, copies both files, no dependencies
tests/
  test_api.py        # 16 integration tests
docker-compose.yml   # backend + frontend + postgres
pyproject.toml       # deps + package config (package under backend/)
PROJECT.md           # this file
README.md            # quick start
.gitignore           # data/, .env, __pycache__, egg-info, build, dist
```

## 4. Configuration

| Variable | Default | Used by | Purpose |
|---|---|---|---|
| `FH_DATA_DIR` | `./data` | compose | host dir for uploads + postgres data |
| `POSTGRES_PASSWORD` | `change_this_later` | compose | set via `.env` on the server |
| `DATABASE_URL` | `postgresql+psycopg://…@postgres:5432/family_health` | backend | SQLAlchemy URL |
| `STORAGE_DIR` | `/data/documents` | backend | where uploads are written |
| `API_URL` | `http://127.0.0.1:18100` | frontend | backend to proxy to (compose: `http://backend:8000`) |
| `HOST` / `PORT` | `127.0.0.1` / `18080` | frontend | bind (compose: `0.0.0.0:80`, container-internal) |

### Ports

- **Temporary dev ports (active):** backend `127.0.0.1:18100`, frontend `127.0.0.1:18080`
- **Actual server ports (commented out in docker-compose.yml):** `8100` / `8080` — restore before deploying
- Security boundary is the left side of the port mapping (`127.0.0.1:…`), never change to `0.0.0.0`
- Postgres publishes no host port
- Swagger: `http://127.0.0.1:8100/docs` (or `:18100/docs` temporarily)

### Server data paths (Ubuntu)

- Documents: `/data/tech-station/family-health/data/documents`
- Postgres: `/data/tech-station/family-health/data/postgres` (or `FH_DATA_DIR`)
- **Never mount or touch `/data/photos`** (Immich lives there)

## 5. Running

Docker (server / intended deployment):

```bash
FH_DATA_DIR=/srv/familyhealth POSTGRES_PASSWORD=secret docker compose up -d --build
```

Local Mac (no Docker):

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
createdb family_health
DATABASE_URL=postgresql+psycopg:///family_health STORAGE_DIR=/tmp/fh-docs \
  uvicorn app.main:app --host 127.0.0.1 --port 18100 &
python frontend/server.py        # UI at 127.0.0.1:18080
```

Tests: `pytest tests/ -q` (16 passing; sqlite + temp STORAGE_DIR, no server needed)

## 6. API reference

Base: proxied through the frontend (same origin, no CORS) or direct.

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status":"ok"}` |
| GET | `/health/db` | `{"database":true}` |
| GET/POST | `/family-members` | list / create `{name, date_of_birth?, gender?}` |
| GET | `/family-members/{id}/prescriptions` | **member-isolated** list, includes `ocr_text` + medicines, newest first |
| POST | `/family-members/{id}/prescriptions` | structured create `{document_path, prescription_date?, doctor_name?, hospital_name?, diagnosis?, notes?, medicines[]}` |
| POST | `/family-members/{id}/prescriptions/upload` | multipart: `file` + optional `prescription_date` (YYYY-MM-DD). Returns `ocr_text`, `ocr_error`, `stored_path` |
| GET | `/prescriptions/{id}/document` | serves the stored file (ext whitelist, jailed to STORAGE_DIR, `nosniff`) |
| PATCH | `/prescriptions/{id}` | partial update: `prescription_date, doctor_name, hospital_name, diagnosis, ocr_text` (omit = untouched, null/"" = clear) |
| DELETE | `/prescriptions/{id}` | deletes record + its medicines + the stored file |
| GET | `/inventory` | list home medicines |
| POST | `/inventory` | add `{medicine_name, quantity?, unit?, expiry_date?, source?}` → 201 |

## 7. Database schema

```
family_members        id, name, date_of_birth, gender, created_at
    │ 1:N
prescriptions         id, family_member_id, document_path, prescription_date,
    │ 1:N             doctor_name, hospital_name, diagnosis, notes, ocr_text, created_at
prescription_medicines id, prescription_id, medicine_name, dosage,
                       frequency, duration, instructions, created_at

medicine_inventory    id, medicine_name, quantity, unit, expiry_date,
                      source, image_path, created_at      ← intentionally separate
```

- `MedicineInventory` is never equated with prescribed medicines
- Schema currently created via `create_all` (container CMD + import) — **Alembic
  required before any schema change on real data; never drop tables**
- `ocr_text` was added 2026-10; existing prod DB already had the column

## 8. OCR pipeline

```
upload → member check → content-type check (jpeg/png/pdf only)
       → save_document (uuid filename into STORAGE_DIR)
       → images only: extract_text() in try/except
            preprocess: grayscale → autocontrast → 4× upscale if <1200px
            tesseract image_to_string
       → single INSERT (ocr_text + notes)
       → respond {ocr_text | ocr_error}
```

Rules (spec §12, all enforced + tested):
- OCR failure **never** loses the document: record is created, `ocr_text=null`,
  `ocr_error` returned, reason stored in `notes` (`OCR failed: …`) for audit
- Never fabricates text; raw text preserved verbatim for reprocessing
- PDFs: stored, no text extraction yet (modular, when needed)
- **Known ceiling:** Tesseract cannot read cursive handwriting (tested — printed
  text is accurate, handwriting is not). Upgrade path: vision-LLM OCR pass,
  which also covers structured extraction. Not built (YAGNI until chatbot phase)

## 9. Frontend

One file (`frontend/index.html`), no framework by explicit requirement:

- Member chips, add-member form
- Upload: date (defaults today) + file; status banner distinguishes
  OCR success / OCR-failed-but-saved / PDF
- Prescription cards: document image inline (PDF → link), medicines,
  collapsible raw OCR text, warning-styled failure notes
- **Edit** (inline): date, doctor, hospital, diagnosis, OCR text correction
- **Delete** (confirm): record + file, via `DELETE`
- **Search:** live client-side filter across all fields incl. OCR text
- **Print for doctor:** `@media print` prints only member + cards + images
- Home inventory: add/list, expiry shown, expired in red
- Light/dark via CSS variables, focus rings, `aria-live` status
- Escapes all interpolated strings (XSS)
- Threshold for abandoning vanilla: ~500 lines or client-side routing needs
  (marked with `ponytail:` comment)

## 10. Testing

`pytest tests/ -q` → 16 tests: health, db health, member create/list,
prescription create + **member isolation**, upload with OCR success,
OCR failure keeps document, invalid file → 400, missing member → 404,
upload with/without date, invalid date → 400, document serving (+ jail
escape → 404), PATCH (partial/null-clear/validation), DELETE (file removed,
medicines cascaded, double-delete → 404), inventory add/list/validation.

Upload tests monkeypatch `extract_text` (no tesseract needed in CI).

## 11. Security posture

Exists:
- Member isolation enforced **in SQL** (`WHERE family_member_id = ?`), never
  fetch-all-then-filter (spec §17 — critical requirement)
- Upload type allow-list; generated uuid filenames; document serving jailed to
  STORAGE_DIR with extension whitelist + `nosniff` (blocks traversal/stored XSS)
- Backend + postgres bound to localhost / unpublished ports
- `.gitignore` blocks `.env`, `data/`, uploads, `__pycache__`; no health data
  or secrets in git (verified before each push)
- No medical content in logs (access logs show paths only)

Missing (spec "eventually", blocks production claim):
- Authentication / authorization / per-member access control
- Audit logging, secret management hardening
- Upload size limit, deep content sniffing of files
- Rate limiting

## 12. Git rules

Never commit: `.env` / `.env.*`, `data/`, uploaded documents, medical images,
Postgres files, API keys, passwords, real family info, `__pycache__/`,
`node_modules/`. Config templates → `.env.example` (not yet created).

Workflow: Mac (VS Code/Claude Code) → git → Ubuntu server → docker compose.
Do not copy production DB to dev; do not copy real documents to git.

## 13. Roadmap (in rough order)

1. Alembic migrations (replace `create_all` before schema evolves) — **before**
   any real schema change; never drop/reset production data
2. Services layer (`backend/app/services/`) when business logic grows —
   routes stay thin: validate → call → format → HTTP errors
3. Structured extraction (OCR text → doctor/medicines/dates, null when unsure,
   never invent) → `extraction_service.py`
4. PDF text extraction (text PDFs) + render-scan-then-OCR (modular, no heavy deps)
5. Inventory: photo input, search
6. Auth + member access control → then claim production-ready
7. Health chatbot: retrieve-only, member-scoped, no prescribing/diagnosing,
   must say "not in the stored record" when missing
8. Agent + MCP tools: `get_family_member`, `get_prescriptions`,
   `get_prescription`, `get_prescription_medicines`, `get_medicine_inventory`,
   `search_health_records` — **no arbitrary SQL/shell/filesystem/Docker**
9. Vision-LLM OCR if handwriting accuracy matters

## 14. Decisions & deviations (deliberate)

- **Python 3.13** everywhere (spec §5 said 3.12; Dockerfile/pyproject aligned to 3.13)
- **pyproject.toml instead of requirements.txt** — one dep source
- **No nginx** — stdlib proxy (explicit requirement), swap only if TLS/buffering needed
- **`frontend/` kept** as its own service, sibling of `backend/` (structure asked for)
- **Compose data paths env-driven** (`FH_DATA_DIR`) so the repo runs anywhere
- **Temp ports active**, real ports commented in `docker-compose.yml`
- Test data/db on dev machines is throwaway; prod paths only on the server
