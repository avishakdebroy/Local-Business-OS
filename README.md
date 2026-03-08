# Local Business OS (MVP)

Offline-first self-hosted app for small shops. It ingests receipts/memos/inventory text or files, auto-structures data with a local LLM, stores in SQLite, runs weekly reports, and performs encrypted-cloud-ready backups.

## Features

- FastAPI app with upload + chat-style text ingestion.
- OCR support for image receipts (Tesseract).
- PDF text extraction.
- Local LLM parsing via Ollama (`/api/generate`).
- SQLite schema for documents, receipts, inventory, memos, and report runs.
- Weekly scheduled report generation + optional email sending.
- Daily backup zip + optional cloud push via `rclone`.

## Quick Start

1. Clone and enter repo.
2. Create virtual environment.
3. Install dependencies.
4. Copy `.env.example` to `.env` and adjust values.
5. Run app.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Required Local Tools

- Python 3.10+
- Ollama (for local LLM)
- Tesseract OCR (for image receipts)
- Optional: rclone (for cloud backup)

## Endpoints

- `GET /health`
- `POST /ingest/text`
- `POST /ingest/file`
- `GET /summary`
- `POST /jobs/run-weekly-report`
- `POST /jobs/run-backup`
- `GET /reports/latest`

## Weekly Report Scheduler

Configured by:

- `REPORT_DAY`
- `REPORT_HOUR`
- `REPORT_MINUTE`
- `APP_TIMEZONE`

Scheduler starts automatically when app starts.

## Backup Strategy

Local zip backups are written to `data/backups/`.

If `RCLONE_REMOTE` is set, backup zip is copied to:

`<RCLONE_REMOTE>:<RCLONE_PATH>`

Use `rclone config` to connect free storage (Google Drive, OneDrive, Dropbox, etc.), and use `rclone crypt` for encryption.

## Notes for Production

- Put this behind a local reverse proxy if needed.
- Add authentication for multi-user use.
- Add validation/review UI for low-confidence extractions.
- Consider SQLite WAL mode and periodic vacuum for larger data volume.
