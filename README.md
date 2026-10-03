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
docker compose up --build
```

- UI: http://127.0.0.1:18080 (`frontend/server.py` serves the UI, proxies
  `/family-members`, `/health`, `/docs` to `backend:8000`)
- API direct: http://127.0.0.1:18100

## Run (local, no Docker)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e .
createdb family_health   # once

DATABASE_URL=postgresql+psycopg:///family_health \
STORAGE_DIR=/tmp/fh-docs \
uvicorn app.main:app --host 127.0.0.1 --port 18100 &

python frontend/server.py   # defaults: 127.0.0.1:18080 → API 18100
```

Python 3.13+ (`.python-version`). Backend image installs `tesseract-ocr`; image
uploads are OCR'd on upload, PDFs are stored without OCR.

## Configuration (paths vary per server)

| Variable | Default | Used by | What |
|---|---|---|---|
| `FH_DATA_DIR` | `./data` | compose | host dir for uploads + postgres data |
| `POSTGRES_PASSWORD` | `change_this_later` | compose | set this, or put it in `.env` |
| `STORAGE_DIR` | `/data/documents` | backend | where uploaded documents are written |
| `DATABASE_URL` | `...@postgres:5432/family_health` | backend | SQLAlchemy URL |
| `API_URL` | `http://127.0.0.1:18100` | frontend | backend to proxy to (compose sets `http://backend:8000`) |
| `HOST` / `PORT` | `127.0.0.1` / `18080` | frontend | bind address (compose sets `0.0.0.0:80`) |

```bash
FH_DATA_DIR=/srv/familyhealth POSTGRES_PASSWORD=secret docker compose up -d
```

Container-internal paths (don't change): volume target `/data/documents`, and
the compose network host `postgres`.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/health/db` | liveness, db check |
| GET/POST | `/family-members` | list / add |
| GET | `/family-members/{id}/prescriptions` | list with medicines |
| POST | `/family-members/{id}/prescriptions` | JSON, `document_path` + `medicines[]` |
| POST | `/family-members/{id}/prescriptions/upload` | multipart file: JPEG/PNG/PDF |
