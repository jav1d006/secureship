import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

from . import config, db, worker

logging.basicConfig(level=logging.INFO)

SCAN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
QUEUE_LEN = Gauge("secureship_queue_length", "Scans waiting in queue")
SCANS = Gauge("secureship_scans", "Scans by status", ["status"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    worker.requeue_unfinished()
    yield


app = FastAPI(title="SecureShip", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    try:
        QUEUE_LEN.set(worker.queue_len())
    except Exception:
        pass
    counts = {k: 0 for k in ("queued", "running", "done", "failed")} | db.count_by_status()
    for k, n in counts.items():
        SCANS.labels(k).set(n)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/scans", status_code=202)
async def create_scan(file: UploadFile = File(...)):
    name = (file.filename or "upload.zip")[:200]
    if not name.lower().endswith(".zip"):
        raise HTTPException(400, "only .zip uploads are supported")
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"file exceeds {config.MAX_UPLOAD_MB} MB")
    scan_id = db.create_scan(name, data)
    worker.enqueue(scan_id)
    return {"id": scan_id, "status": "queued"}


@app.get("/api/scans")
def list_scans():
    return db.list_scans()


@app.get("/api/scans/{scan_id}")
def get_scan(scan_id: str):
    if not SCAN_ID_RE.match(scan_id):
        raise HTTPException(404, "scan not found")
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(404, "scan not found")
    return scan
