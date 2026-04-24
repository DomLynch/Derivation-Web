"""JSON API routes. This is the Researka wire contract — see INTEGRATION.md."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from derivation_web.core.graph import walk_provenance
from derivation_web.core.hashing import content_hash, step_hash
from derivation_web.core.models import (
    ANNOTATION_STEP_TYPES,
    Actor,
    ActorCreate,
    Artifact,
    ArtifactCreate,
    Step,
    StepCreate,
)
from derivation_web.core.signing import verify
from derivation_web.db import repo
from derivation_web.db.session import get_session

router = APIRouter(tags=["derivation"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_FUTURE_CLOCK_SKEW = timedelta(seconds=60)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@router.post("/actors", response_model=Actor, status_code=status.HTTP_201_CREATED)
def create_actor(payload: ActorCreate, session: SessionDep) -> Actor:
    if repo.get_actor(session, payload.id) is not None:
        raise HTTPException(409, f"actor {payload.id!r} already exists")
    actor = Actor(
        id=payload.id,
        kind=payload.kind,
        name=payload.name,
        pubkey_ed25519_b64=payload.pubkey_ed25519_b64,
    )
    repo.insert_actor(session, actor)
    session.commit()
    return actor


@router.get("/actors/{actor_id}", response_model=Actor)
def get_actor(actor_id: str, session: SessionDep) -> Actor:
    actor = repo.get_actor(session, actor_id)
    if actor is None:
        raise HTTPException(404, f"actor {actor_id!r} not found")
    return actor


@router.post(
    "/artifacts", response_model=Artifact, status_code=status.HTTP_201_CREATED
)
def create_artifact(payload: ArtifactCreate, session: SessionDep) -> Artifact:
    if repo.get_actor(session, payload.actor_id) is None:
        raise HTTPException(400, f"unknown actor {payload.actor_id!r}")

    ch = content_hash(
        kind=payload.kind.value,
        content_type=payload.content_type,
        body_text=payload.body_text,
        body_base64=payload.body_base64,
        metadata=payload.metadata,
    )
    existing = repo.get_artifact_by_hash_and_actor(session, ch, payload.actor_id)
    if existing is not None:
        return existing

    artifact = Artifact(
        id=_new_id("art"),
        kind=payload.kind,
        content_type=payload.content_type,
        body_text=payload.body_text,
        body_base64=payload.body_base64,
        metadata=payload.metadata,
        content_hash=ch,
        actor_id=payload.actor_id,
        created_at=datetime.now(UTC),
    )
    repo.insert_artifact(session, artifact)
    session.commit()
    return artifact


@router.get("/artifacts/{artifact_id}", response_model=Artifact)
def get_artifact_route(artifact_id: str, session: SessionDep) -> Artifact:
    artifact = repo.get_artifact(session, artifact_id)
    if artifact is None:
        raise HTTPException(404, f"artifact {artifact_id!r} not found")
    return artifact


def _validate_step_created_at(created_at: datetime) -> None:
    now = datetime.now(UTC)
    if created_at.tzinfo is None:
        raise HTTPException(400, "created_at must be timezone-aware")
    if created_at > now + MAX_FUTURE_CLOCK_SKEW:
        raise HTTPException(
            400,
            "created_at is too far in the future (>60s clock skew allowed)",
        )


@router.post("/steps", response_model=Step, status_code=status.HTTP_201_CREATED)
def create_step(payload: StepCreate, session: SessionDep) -> Step:
    _validate_step_created_at(payload.created_at)

    actor = repo.get_actor(session, payload.actor_id)
    if actor is None:
        raise HTTPException(400, f"unknown actor {payload.actor_id!r}")
    for aid in payload.input_artifact_ids:
        if repo.get_artifact(session, aid) is None:
            raise HTTPException(400, f"unknown input artifact {aid!r}")
    if repo.get_artifact(session, payload.output_artifact_id) is None:
        raise HTTPException(
            400, f"unknown output artifact {payload.output_artifact_id!r}"
        )
    if (
        payload.target_artifact_id is not None
        and repo.get_artifact(session, payload.target_artifact_id) is None
    ):
        raise HTTPException(
            400, f"unknown target artifact {payload.target_artifact_id!r}"
        )
    if payload.step_type in ANNOTATION_STEP_TYPES:
        assert payload.target_artifact_id is not None  # enforced by model_validator
        if payload.target_artifact_id == payload.output_artifact_id:
            raise HTTPException(
                400, "target_artifact_id must differ from output_artifact_id"
            )
    if repo.get_producing_step(session, payload.output_artifact_id) is not None:
        raise HTTPException(409, "output artifact already has a producing step")

    sh = step_hash(
        step_type=payload.step_type.value,
        input_artifact_ids=payload.input_artifact_ids,
        output_artifact_id=payload.output_artifact_id,
        target_artifact_id=payload.target_artifact_id,
        actor_id=payload.actor_id,
        method=payload.method,
        created_at=payload.created_at,
    )
    if payload.signature_b64 is not None:
        if actor.pubkey_ed25519_b64 is None:
            raise HTTPException(
                400, "signature provided but actor has no pubkey on file"
            )
        if not verify(actor.pubkey_ed25519_b64, sh, payload.signature_b64):
            raise HTTPException(400, "signature verification failed")

    step = Step(
        id=_new_id("step"),
        step_type=payload.step_type,
        input_artifact_ids=payload.input_artifact_ids,
        output_artifact_id=payload.output_artifact_id,
        target_artifact_id=payload.target_artifact_id,
        actor_id=payload.actor_id,
        method=payload.method,
        step_hash=sh,
        signature_b64=payload.signature_b64,
        created_at=payload.created_at,
    )
    repo.insert_step(session, step)
    session.commit()
    return step


@router.get("/artifacts/{artifact_id}/chain")
def get_chain(artifact_id: str, session: SessionDep) -> dict[str, Any]:
    if repo.get_artifact(session, artifact_id) is None:
        raise HTTPException(404, f"artifact {artifact_id!r} not found")

    nodes = walk_provenance(
        root_artifact_id=artifact_id,
        get_artifact=lambda aid: repo.get_artifact(session, aid),
        get_producing_step=lambda aid: repo.get_producing_step(session, aid),
    )

    out: list[dict[str, Any]] = []
    for node in nodes:
        challenges, revisions = repo.get_annotations(session, node.artifact.id)
        out.append(
            {
                "artifact": node.artifact.model_dump(mode="json"),
                "producing_step": (
                    node.producing_step.model_dump(mode="json")
                    if node.producing_step
                    else None
                ),
                "depth": node.depth,
                "challenges": [
                    {
                        "artifact": a.model_dump(mode="json"),
                        "step": s.model_dump(mode="json"),
                    }
                    for a, s in challenges
                ],
                "revisions": [
                    {
                        "artifact": a.model_dump(mode="json"),
                        "step": s.model_dump(mode="json"),
                    }
                    for a, s in revisions
                ],
            }
        )
    return {"root_id": artifact_id, "nodes": out}
