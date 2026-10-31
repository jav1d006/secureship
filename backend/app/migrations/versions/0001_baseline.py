"""baseline: scans table (idempotent, so existing databases adopt it as-is)

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS scans (
        id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL, score INTEGER,
        result JSONB, error TEXT, upload BYTEA, created_at TEXT NOT NULL, finished_at TEXT)""")
    for col in ("scanners TEXT", "owner TEXT", "started_at TEXT", "attempts INTEGER NOT NULL DEFAULT 0", "share_token TEXT"):
        op.execute(f"ALTER TABLE scans ADD COLUMN IF NOT EXISTS {col}")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS scans_share ON scans (share_token) WHERE share_token IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS scans_owner_created ON scans (owner, created_at DESC)")
