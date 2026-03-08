from __future__ import annotations

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse

from app.db import init_db, get_conn
from app.schemas import TextIngestRequest, IngestResponse, JobRunResponse
from app.services.storage import ensure_app_dirs, save_upload
from app.services.ocr import extract_text
from app.services.ingest import ingest_text
from app.services.reporting import run_weekly_report
from app.services.backup import run_backup
from app.jobs.scheduler import start_scheduler, shutdown_scheduler


app = FastAPI(title="Local Business OS", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    ensure_app_dirs()
    init_db()
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    shutdown_scheduler()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
    <html>
      <head><title>Local Business OS</title></head>
      <body style="font-family: sans-serif; max-width: 900px; margin: 2rem auto;">
        <h1>Local Business OS</h1>
        <p>Upload receipts/memos/inventory docs or send chat text for auto-structuring.</p>

        <h2>Upload a file</h2>
        <form action="/ingest/file" method="post" enctype="multipart/form-data">
          <input type="file" name="file" required />
          <select name="doc_type">
            <option value="auto">auto</option>
            <option value="receipt">receipt</option>
            <option value="inventory">inventory</option>
            <option value="memo">memo</option>
          </select>
          <button type="submit">Upload</button>
        </form>

        <h2>Send text</h2>
        <form action="/ingest/text-form" method="post">
          <textarea name="text" rows="6" cols="80" required></textarea><br/>
          <select name="doc_type">
            <option value="auto">auto</option>
            <option value="receipt">receipt</option>
            <option value="inventory">inventory</option>
            <option value="memo">memo</option>
          </select>
          <button type="submit">Submit</button>
        </form>
      </body>
    </html>
    """


@app.post("/ingest/text", response_model=IngestResponse)
def ingest_text_api(payload: TextIngestRequest) -> IngestResponse:
    result = ingest_text(payload.text, requested_type=payload.doc_type)
    return IngestResponse(
        document_id=result["document_id"],
        inferred_type=result["inferred_type"],
        confidence=float(result["confidence"]),
        message="Text processed",
    )


@app.post("/ingest/text-form")
def ingest_text_form(text: str = Form(...), doc_type: str = Form("auto")) -> dict:
    result = ingest_text(text, requested_type=doc_type)
    return {"status": "ok", **result}


@app.post("/ingest/file", response_model=IngestResponse)
def ingest_file(file: UploadFile = File(...), doc_type: str = Form("auto")) -> IngestResponse:
    saved = save_upload(file)
    text = extract_text(saved)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    result = ingest_text(text, requested_type=doc_type, file_path=str(saved))
    return IngestResponse(
        document_id=result["document_id"],
        inferred_type=result["inferred_type"],
        confidence=float(result["confidence"]),
        message=f"File processed: {saved.name}",
    )


@app.get("/reports/latest")
def latest_report() -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM report_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {"status": "empty", "detail": "No report generated yet"}
        return {k: row[k] for k in row.keys()}


@app.post("/jobs/run-weekly-report", response_model=JobRunResponse)
def run_weekly_report_now() -> JobRunResponse:
    out = run_weekly_report()
    return JobRunResponse(status=out["status"], detail=out["report_path"])


@app.post("/jobs/run-backup", response_model=JobRunResponse)
def run_backup_now() -> JobRunResponse:
    out = run_backup()
    return JobRunResponse(status=out["status"], detail=out["backup_path"])


@app.get("/summary")
def summary() -> dict:
    with get_conn() as conn:
        counts = {}
        for table in ["documents", "receipts", "inventory_items", "inventory_moves", "memos", "report_runs"]:
            counts[table] = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    return counts
