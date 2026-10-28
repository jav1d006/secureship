import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "secureship.db"
WORK_DIR = Path(os.getenv("WORK_DIR", str(DATA_DIR / "work")))

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_UNZIPPED_MB = int(os.getenv("MAX_UNZIPPED_MB", "100"))
MAX_FILES = int(os.getenv("MAX_FILES", "5000"))
SCAN_TIMEOUT_SEC = int(os.getenv("SCAN_TIMEOUT_SEC", "120"))

GITLEAKS_BIN = os.getenv("GITLEAKS_BIN", "gitleaks")
CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o]

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://secureship:secureship@localhost:5432/secureship")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://secureship:secureship@localhost:5432/secureship")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
