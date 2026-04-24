"""initial schema: actors, artifacts, steps

Revision ID: 0001
Revises:
Create Date: 2026-04-24

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "actors",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("pubkey_ed25519_b64", sa.String(128), nullable=True),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("body_base64", sa.Text, nullable=True),
        sa.Column("artifact_metadata", sa.JSON, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "actor_id",
            sa.String(128),
            sa.ForeignKey("actors.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "content_hash", "actor_id", name="uq_artifacts_hash_actor"
        ),
    )
    op.create_index("ix_artifacts_kind", "artifacts", ["kind"])
    op.create_index("ix_artifacts_content_hash", "artifacts", ["content_hash"])
    op.create_table(
        "steps",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("step_type", sa.String(32), nullable=False),
        sa.Column(
            "input_artifact_ids",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
        ),
        sa.Column(
            "output_artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "target_artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id"),
            nullable=True,
        ),
        sa.Column(
            "actor_id",
            sa.String(128),
            sa.ForeignKey("actors.id"),
            nullable=False,
        ),
        sa.Column("method", sa.JSON, nullable=False),
        sa.Column("step_hash", sa.String(64), nullable=False),
        sa.Column("signature_b64", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_steps_step_type", "steps", ["step_type"])
    op.create_index("ix_steps_step_hash", "steps", ["step_hash"])
    op.create_index(
        "ix_steps_output_artifact_id",
        "steps",
        ["output_artifact_id"],
        unique=True,
    )
    op.create_index(
        "ix_steps_target_artifact_id", "steps", ["target_artifact_id"]
    )
    op.execute(
        "CREATE INDEX ix_steps_input_ids_gin "
        "ON steps USING gin (input_artifact_ids)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_steps_input_ids_gin")
    op.drop_table("steps")
    op.drop_table("artifacts")
    op.drop_table("actors")
