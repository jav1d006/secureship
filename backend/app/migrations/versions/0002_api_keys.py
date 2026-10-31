"""api_keys table

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE, creator TEXT NOT NULL,
        name TEXT NOT NULL, prefix TEXT NOT NULL, created_at TEXT NOT NULL,
        last_used_at TEXT, revoked_at TEXT)""")
    op.execute("CREATE INDEX IF NOT EXISTS api_keys_creator ON api_keys (creator)")
