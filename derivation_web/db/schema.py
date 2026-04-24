"""SQLAlchemy 2.0 ORM. Postgres-specific (ARRAY column)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ActorRow(Base):
    __tablename__ = "actors"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    pubkey_ed25519_b64: Mapped[str | None] = mapped_column(String(128))


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "content_hash", "actor_id", name="uq_artifacts_hash_actor"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)
    body_base64: Mapped[str | None] = mapped_column(Text)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("actors.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class StepRow(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    step_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    input_artifact_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False
    )
    output_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    target_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True, index=True
    )
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("actors.id"), nullable=False
    )
    method: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    step_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signature_b64: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
