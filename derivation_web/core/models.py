"""Pure domain models. No DB, no HTTP dependencies."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_ARTIFACT_BYTES = 10 * 1024 * 1024


def utcnow() -> datetime:
    return datetime.now(UTC)


class ArtifactKind(StrEnum):
    SOURCE = "source"
    CLAIM = "claim"
    CHALLENGE = "challenge"
    REVISION = "revision"


class ActorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    MODEL = "model"
    SYSTEM = "system"


class StepType(StrEnum):
    SUMMARIZE = "summarize"
    EXTRACT = "extract"
    INFER = "infer"
    CALCULATE = "calculate"
    CLASSIFY = "classify"
    COMPARE = "compare"
    REVISE = "revise"
    CHALLENGE = "challenge"


ANNOTATION_STEP_TYPES: frozenset[StepType] = frozenset(
    {StepType.CHALLENGE, StepType.REVISE}
)


class Actor(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: ActorKind
    name: str
    pubkey_ed25519_b64: str | None = None


class ActorCreate(BaseModel):
    id: str
    kind: ActorKind = ActorKind.HUMAN
    name: str
    pubkey_ed25519_b64: str | None = None


def _validate_artifact_body(
    body_text: str | None, body_base64: str | None
) -> None:
    has_text = body_text is not None
    has_b64 = body_base64 is not None
    if has_text == has_b64:
        raise ValueError(
            "artifact must carry exactly one of body_text or body_base64"
        )
    size = (
        len(body_text.encode("utf-8")) if body_text is not None else len(body_base64 or "")
    )
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"artifact body exceeds {MAX_ARTIFACT_BYTES} bytes (utf-8 encoded)"
        )


class Artifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: ArtifactKind
    content_type: str
    body_text: str | None = None
    body_base64: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    actor_id: str
    created_at: datetime


class ArtifactCreate(BaseModel):
    kind: ArtifactKind
    content_type: str = "text/plain"
    body_text: str | None = None
    body_base64: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    actor_id: str

    @model_validator(mode="after")
    def _check_body(self) -> ArtifactCreate:
        _validate_artifact_body(self.body_text, self.body_base64)
        return self


def _validate_step_shape(
    step_type: StepType,
    input_artifact_ids: list[str],
    target_artifact_id: str | None,
) -> None:
    if step_type in ANNOTATION_STEP_TYPES:
        if target_artifact_id is None:
            raise ValueError(
                f"{step_type.value!r} step requires target_artifact_id"
            )
    else:
        if target_artifact_id is not None:
            raise ValueError(
                f"{step_type.value!r} step must not set target_artifact_id"
            )
        if not input_artifact_ids:
            raise ValueError(
                f"{step_type.value!r} step requires at least one input_artifact_id"
            )


class Step(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    step_type: StepType
    input_artifact_ids: list[str]
    output_artifact_id: str
    target_artifact_id: str | None = None
    actor_id: str
    method: dict[str, Any] = Field(default_factory=dict)
    step_hash: str
    signature_b64: str | None = None
    created_at: datetime


class StepCreate(BaseModel):
    step_type: StepType
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_id: str
    target_artifact_id: str | None = None
    actor_id: str
    method: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    signature_b64: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> StepCreate:
        _validate_step_shape(
            self.step_type, self.input_artifact_ids, self.target_artifact_id
        )
        return self


__all__ = [
    "ANNOTATION_STEP_TYPES",
    "MAX_ARTIFACT_BYTES",
    "Actor",
    "ActorCreate",
    "ActorKind",
    "Artifact",
    "ArtifactCreate",
    "ArtifactKind",
    "Step",
    "StepCreate",
    "StepType",
    "utcnow",
]
