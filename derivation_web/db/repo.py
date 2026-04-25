"""Repository: SQL rows ↔ core Pydantic models. Transaction boundaries live in routes."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from derivation_web.core.models import (
    ANNOTATION_STEP_TYPES,
    Actor,
    ActorKind,
    ApiKey,
    Artifact,
    ArtifactKind,
    Step,
    StepType,
)
from derivation_web.db.schema import ActorRow, ApiKeyRow, ArtifactRow, StepRow


def _to_actor(row: ActorRow) -> Actor:
    return Actor(
        id=row.id,
        kind=ActorKind(row.kind),
        name=row.name,
        pubkey_ed25519_b64=row.pubkey_ed25519_b64,
    )


def _to_artifact(row: ArtifactRow) -> Artifact:
    return Artifact(
        id=row.id,
        kind=ArtifactKind(row.kind),
        content_type=row.content_type,
        body_text=row.body_text,
        body_base64=row.body_base64,
        metadata=row.artifact_metadata,
        content_hash=row.content_hash,
        actor_id=row.actor_id,
        created_at=row.created_at,
    )


def _to_step(row: StepRow) -> Step:
    return Step(
        id=row.id,
        step_type=StepType(row.step_type),
        input_artifact_ids=list(row.input_artifact_ids),
        output_artifact_id=row.output_artifact_id,
        target_artifact_id=row.target_artifact_id,
        actor_id=row.actor_id,
        method=row.method,
        step_hash=row.step_hash,
        signature_b64=row.signature_b64,
        created_at=row.created_at,
    )


def get_actor(session: Session, actor_id: str) -> Actor | None:
    row = session.get(ActorRow, actor_id)
    return _to_actor(row) if row else None


def insert_actor(session: Session, actor: Actor) -> None:
    session.add(
        ActorRow(
            id=actor.id,
            kind=actor.kind.value,
            name=actor.name,
            pubkey_ed25519_b64=actor.pubkey_ed25519_b64,
        )
    )


def get_artifact(session: Session, artifact_id: str) -> Artifact | None:
    row = session.get(ArtifactRow, artifact_id)
    return _to_artifact(row) if row else None


def get_artifact_by_hash_and_actor(
    session: Session, content_hash: str, actor_id: str
) -> Artifact | None:
    """Dedupe lookup scoped to (content, actor).

    Cross-actor submissions with identical content are NOT merged — each actor
    gets their own attributed row. This preserves creator provenance.
    """
    stmt = select(ArtifactRow).where(
        ArtifactRow.content_hash == content_hash,
        ArtifactRow.actor_id == actor_id,
    )
    row = session.scalars(stmt).first()
    return _to_artifact(row) if row else None


def insert_artifact(session: Session, artifact: Artifact) -> None:
    session.add(
        ArtifactRow(
            id=artifact.id,
            kind=artifact.kind.value,
            content_type=artifact.content_type,
            body_text=artifact.body_text,
            body_base64=artifact.body_base64,
            artifact_metadata=artifact.metadata,
            content_hash=artifact.content_hash,
            actor_id=artifact.actor_id,
            created_at=artifact.created_at,
        )
    )


def insert_step(session: Session, step: Step) -> None:
    session.add(
        StepRow(
            id=step.id,
            step_type=step.step_type.value,
            input_artifact_ids=list(step.input_artifact_ids),
            output_artifact_id=step.output_artifact_id,
            target_artifact_id=step.target_artifact_id,
            actor_id=step.actor_id,
            method=step.method,
            step_hash=step.step_hash,
            signature_b64=step.signature_b64,
            created_at=step.created_at,
        )
    )


def get_producing_step(session: Session, artifact_id: str) -> Step | None:
    stmt = select(StepRow).where(StepRow.output_artifact_id == artifact_id)
    row = session.scalars(stmt).first()
    return _to_step(row) if row else None


def _to_api_key(row: ApiKeyRow) -> ApiKey:
    return ApiKey(
        id=row.id,
        key_hash=row.key_hash,
        client_id=row.client_id,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


def create_api_key(
    session: Session, *, key_id: str, key_hash: str, client_id: str
) -> None:
    session.add(
        ApiKeyRow(
            id=key_id,
            key_hash=key_hash,
            client_id=client_id,
            created_at=datetime.now(UTC),
            revoked_at=None,
        )
    )


def find_active_api_key_by_hash(
    session: Session, key_hash: str
) -> ApiKey | None:
    stmt = select(ApiKeyRow).where(
        ApiKeyRow.key_hash == key_hash,
        ApiKeyRow.revoked_at.is_(None),
    )
    row = session.scalars(stmt).first()
    return _to_api_key(row) if row else None


def revoke_api_key(session: Session, key_id: str) -> bool:
    """Atomically revoke an active key.

    Single UPDATE conditional on `revoked_at IS NULL`, returns whether
    a row was changed. Two concurrent revoke calls cannot both succeed
    (the second sees rowcount=0 and returns False), which preserves
    audit truth: there is exactly one revoked_at timestamp.
    """
    from sqlalchemy import CursorResult, update

    result: CursorResult[ApiKeyRow] = session.execute(  # type: ignore[assignment]
        update(ApiKeyRow)
        .where(ApiKeyRow.id == key_id, ApiKeyRow.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return bool(result.rowcount)


def list_api_keys(session: Session) -> list[ApiKey]:
    stmt = select(ApiKeyRow).order_by(ApiKeyRow.created_at)
    return [_to_api_key(row) for row in session.scalars(stmt).all()]


def get_annotations(
    session: Session, artifact_id: str
) -> tuple[list[tuple[Artifact, Step]], list[tuple[Artifact, Step]]]:
    """Return (challenges, revisions) whose target is this artifact.

    Uses `steps.target_artifact_id` — NOT input_artifact_ids — so evidence
    inputs are not confused with the challenged/revised target.
    """
    annotation_types = [t.value for t in ANNOTATION_STEP_TYPES]
    stmt = (
        select(StepRow, ArtifactRow)
        .join(ArtifactRow, ArtifactRow.id == StepRow.output_artifact_id)
        .where(
            StepRow.target_artifact_id == artifact_id,
            StepRow.step_type.in_(annotation_types),
        )
        .order_by(StepRow.created_at)
    )
    challenges: list[tuple[Artifact, Step]] = []
    revisions: list[tuple[Artifact, Step]] = []
    for step_row, art_row in session.execute(stmt):
        pair = (_to_artifact(art_row), _to_step(step_row))
        if step_row.step_type == StepType.CHALLENGE.value:
            challenges.append(pair)
        else:
            revisions.append(pair)
    return challenges, revisions
