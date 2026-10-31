import os
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
WORK_DIR = Path(os.getenv("WORK_DIR", str(DATA_DIR / "work")))

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_UNZIPPED_MB = int(os.getenv("MAX_UNZIPPED_MB", "100"))
MAX_FILES = int(os.getenv("MAX_FILES", "5000"))
SCAN_TIMEOUT_SEC = int(os.getenv("SCAN_TIMEOUT_SEC", "120"))
# How many memory-hungry scanners (Semgrep, Checkov) may run at the same time inside one worker.
HEAVY_CONCURRENCY = int(os.getenv("HEAVY_CONCURRENCY", "1"))

GITLEAKS_BIN = os.getenv("GITLEAKS_BIN", "gitleaks")
TRIVY_BIN = os.getenv("TRIVY_BIN", "trivy")
SEMGREP_BIN = os.getenv("SEMGREP_BIN", "/opt/semgrep/bin/semgrep")
SEMGREP_RULES = Path(os.getenv("SEMGREP_RULES", "/opt/semgrep-rules"))
CHECKOV_BIN = os.getenv("CHECKOV_BIN", "/opt/checkov/bin/checkov")
SHELLCHECK_BIN = os.getenv("SHELLCHECK_BIN", "shellcheck")

CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o]

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://secureship:secureship@localhost:5432/secureship")
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))


def _redis_url() -> str:
    """REDIS_URL, with REDIS_PASSWORD injected when the URL carries no credentials."""
    parts = urlsplit(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    pw = os.getenv("REDIS_PASSWORD", "")
    if pw and "@" not in parts.netloc:
        parts = parts._replace(netloc=f":{quote(pw, safe='')}@{parts.netloc}")
    return urlunsplit(parts)


REDIS_URL = _redis_url()

MAX_API_KEYS = int(os.getenv("MAX_API_KEYS", "5"))
RATE_SCANS_PER_HOUR = int(os.getenv("RATE_SCANS_PER_HOUR", "10"))
RATE_SCANS_PER_HOUR_IP = int(os.getenv("RATE_SCANS_PER_HOUR_IP", "30"))
RATE_READS_PER_MIN = int(os.getenv("RATE_READS_PER_MIN", "240"))
MAX_QUEUE = int(os.getenv("MAX_QUEUE", "50"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Reliability: a scan is retried at most MAX_ATTEMPTS times; one that stays "running"
# longer than STUCK_AFTER_SEC (> job timeout) is considered dead. Finished scans are
# deleted after RETENTION_DAYS. maintain() runs every MAINTENANCE_INTERVAL_SEC.
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))
STUCK_AFTER_SEC = int(os.getenv("STUCK_AFTER_SEC", "900"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "30"))
MAINTENANCE_INTERVAL_SEC = int(os.getenv("MAINTENANCE_INTERVAL_SEC", "300"))

# --- Scan sandbox -------------------------------------------------------------------------
# "local": scanners run inside the worker pod (default). "job": every scan runs in its own
# Kubernetes Job with no network, no credentials and a read-only source mount (see docs/SANDBOX.md).
SANDBOX_MODE = os.getenv("SANDBOX_MODE", "local")
SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "ghcr.io/jav1d006/secureship-backend:latest")
SANDBOX_NAMESPACE = os.getenv("SANDBOX_NAMESPACE", "secureship")
SANDBOX_NODE = os.getenv("SANDBOX_NODE", "node1")                    # must match the node holding the shared volume
SANDBOX_PVC = os.getenv("SANDBOX_PVC", "scan-work")
SANDBOX_WORK_DIR = Path(os.getenv("SANDBOX_WORK_DIR", "/scan-work"))  # where the worker mounts that volume
SANDBOX_JOB_TIMEOUT = int(os.getenv("SANDBOX_JOB_TIMEOUT", "600"))

# --- E-mail (optional: unset SMTP_HOST disables "send report by e-mail") --------------------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "SecureShip <noreply@localhost>")
RATE_EMAILS_PER_HOUR = int(os.getenv("RATE_EMAILS_PER_HOUR", "5"))
