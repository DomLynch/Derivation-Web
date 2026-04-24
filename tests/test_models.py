"""Model-level validation for the wire contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from derivation_web.core.models import (
    MAX_ARTIFACT_BYTES,
    ArtifactCreate,
    ArtifactKind,
    StepCreate,
    StepType,
)


def test_artifact_rejects_both_body_fields():
    with pytest.raises(ValidationError) as exc:
        ArtifactCreate(
            kind=ArtifactKind.SOURCE,
            body_text="a",
            body_base64="b",
            actor_id="a1",
        )
    assert "exactly one" in str(exc.value)


def test_artifact_rejects_neither_body_field():
    with pytest.raises(ValidationError) as exc:
        ArtifactCreate(kind=ArtifactKind.SOURCE, actor_id="a1")
    assert "exactly one" in str(exc.value)


def test_artifact_measures_utf8_bytes_not_chars():
    # A multibyte char that would sneak past a char-length check.
    huge = "€" * (MAX_ARTIFACT_BYTES // 2)  # 3 bytes per char, so ~1.5x cap in bytes
    with pytest.raises(ValidationError) as exc:
        ArtifactCreate(
            kind=ArtifactKind.SOURCE, body_text=huge, actor_id="a1"
        )
    assert "exceeds" in str(exc.value)


def test_artifact_accepts_at_cap():
    just_fits = "a" * MAX_ARTIFACT_BYTES
    ArtifactCreate(
        kind=ArtifactKind.SOURCE, body_text=just_fits, actor_id="a1"
    )


def test_challenge_requires_target():
    with pytest.raises(ValidationError) as exc:
        StepCreate(
            step_type=StepType.CHALLENGE,
            input_artifact_ids=[],
            output_artifact_id="out",
            target_artifact_id=None,
            actor_id="a1",
            created_at=datetime.now(UTC),
        )
    assert "target_artifact_id" in str(exc.value)


def test_summarize_forbids_target():
    with pytest.raises(ValidationError) as exc:
        StepCreate(
            step_type=StepType.SUMMARIZE,
            input_artifact_ids=["src"],
            output_artifact_id="out",
            target_artifact_id="some_art",
            actor_id="a1",
            created_at=datetime.now(UTC),
        )
    assert "must not set target_artifact_id" in str(exc.value)


def test_non_annotation_requires_inputs():
    with pytest.raises(ValidationError) as exc:
        StepCreate(
            step_type=StepType.SUMMARIZE,
            input_artifact_ids=[],
            output_artifact_id="out",
            actor_id="a1",
            created_at=datetime.now(UTC),
        )
    assert "at least one input_artifact_id" in str(exc.value)


def test_challenge_inputs_may_be_empty():
    StepCreate(
        step_type=StepType.CHALLENGE,
        input_artifact_ids=[],
        output_artifact_id="out",
        target_artifact_id="claim",
        actor_id="a1",
        created_at=datetime.now(UTC),
    )
