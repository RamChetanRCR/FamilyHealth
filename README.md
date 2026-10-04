# Family Health

Family member records + prescription upload with OCR (Tesseract).

## Layout

```
backend/          FastAPI app (package `app`), Dockerfile
frontend/         static HTML/JS UI + stdlib proxy/server (no nginx, no deps)
docker-compose.yml
pyproject.toml    single source of dependencies
```

## Ports (temporary)

Actual server ports are commented out in `docker-compose.yml` (`8100` backend,
`8080` frontend) — restore them when deploying. Temporary dev ports for now:

- UI + proxied API: http://127.0.0.1:18080
- API direct / Swagger: http://127.0.0.1:18100, http://127.0.0.1:18100/docs

## Run (Docker)

```bash
cp .env.example .env     # set FH_DATA_DIR (required, no fallback)
docker compose up --build
```

The backend container runs `alembic upgrade head` before serving, so the schema
is always migrated to the latest revision on start.

- UI: http://127.0.0.1:18080 (`frontend/server.py` serves the UI, proxies
  `/family-members`, `/health`, `/docs` to `backend:8000`)
- API direct: http://127.0.0.1:18100

## Run (local, no Docker)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e .

export STORAGE_DIR=/tmp/fh-docs            # DATABASE_URL defaults to ./family_health.db
alembic upgrade head        # create/upgrade the SQLite schema (not create_all)
uvicorn app.main:app --host 127.0.0.1 --port 18100 &

python frontend/server.py   # defaults: 127.0.0.1:18080 → API 18100
```

Python 3.13+ (`.python-version`). Backend image installs `tesseract-ocr`; image
uploads are OCR'd on upload, PDFs are stored without OCR. Tests: `pytest` (uses
SQLite, applies the migrations, mocks OCR — no Tesseract needed).

**Existing database created by the old `create_all`/`init_db`?** One-time, to
adopt migrations without touching data:
`alembic stamp b65e363410b7 && alembic upgrade head`
(stamps the baseline it already matches, then adds the `ocr_error`/`ocr_edited`
columns). A brand-new database just needs `alembic upgrade head`.

## Configuration (paths vary per server)

| Variable | Default | Used by | What |
|---|---|---|---|
| `FH_DATA_DIR` | — (required) | compose | host dir mounted to `/data`, holding the SQLite DB + uploads; prod `/data/tech-station/family-health/data`. No `./data` fallback. |
| `STORAGE_DIR` | `/data/documents` | backend | where uploaded documents are written |
| `DATABASE_URL` | `sqlite:///./family_health.db` | backend | SQLAlchemy URL (compose sets `sqlite:////data/family_health.db`) |
| `API_URL` | `http://127.0.0.1:18100` | frontend | backend to proxy to (compose sets `http://backend:8000`) |
| `HOST` / `PORT` | `127.0.0.1` / `18080` | frontend | bind address (compose sets `0.0.0.0:80`) |

```bash
FH_DATA_DIR=/srv/familyhealth docker compose up -d
```

Container-internal paths (don't change): the volume mount target `/data` (holds
`family_health.db` and `documents/`).

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/health/db` | liveness, db check |
| GET/POST | `/family-members` | list / add |
| GET | `/family-members/{id}/prescriptions` | list with medicines + OCR status |
| POST | `/family-members/{id}/prescriptions` | JSON, `document_path` + `medicines[]` |
| POST | `/family-members/{id}/prescriptions/upload` | multipart: JPEG/PNG/PDF, content-validated (not just MIME) |
| PATCH | `/family-members/{id}/prescriptions/{pid}` | edit fields; setting `ocr_text` marks it manually edited |
| POST | `/family-members/{id}/prescriptions/{pid}/ocr` | re-run OCR on the stored document (no new record) |
| GET | `/family-members/{id}/prescriptions/{pid}/document` | serve the stored file (STORAGE_DIR-only) |
| DELETE | `/family-members/{id}/prescriptions/{pid}` | delete record, medicines, and stored file |
| GET/POST | `/inventory` | home medicine inventory |

Prescription routes are nested under their family member: every one loads the
record only if it belongs to `{id}` (one ownership boundary, ready for auth).
