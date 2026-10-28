import logging
import re
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import config, db, worker

logging.basicConfig(level=logging.INFO)

SCAN_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    worker.start()
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
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/scans", status_code=202)
async def create_scan(file: UploadFile = File(...)):
    name = (file.filename or "upload.zip")[:200]
    if not name.lower().endswith(".zip"):
        raise HTTPException(400, "only .zip uploads are supported")

    scan_id = db.create_scan(name)
    scan_dir = config.WORK_DIR / scan_id
    scan_dir.mkdir(parents=True, exist_ok=True)

    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    written = 0
    with open(scan_dir / "upload.zip", "wb") as out:
        while chunk := await file.read(64 * 1024):
            written += len(chunk)
            if written > limit:
                out.close()
                shutil.rmtree(scan_dir, ignore_errors=True)
                db.set_failed(scan_id, "upload too large")
                raise HTTPException(413, f"file exceeds {config.MAX_UPLOAD_MB} MB")
            out.write(chunk)

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
