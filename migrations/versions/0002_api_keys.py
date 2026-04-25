"""api_keys: transport auth for write endpoints

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")
