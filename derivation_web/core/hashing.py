"""Content and step hashing."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from derivation_web.core.canonical import canonicalize


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(
    *,
    kind: str,
    content_type: str,
    body_text: str | None,
    body_base64: str | None,
    metadata: dict[str, Any],
) -> str:
    payload = {
        "kind": kind,
        "content_type": content_type,
        "body_text": body_text,
        "body_base64": body_base64,
        "metadata": metadata,
    }
    return _sha256_hex(canonicalize(payload))


def step_hash(
    *,
    step_type: str,
    input_artifact_ids: list[str],
    output_artifact_id: str,
    target_artifact_id: str | None,
    actor_id: str,
    method: dict[str, Any],
    created_at: datetime,
) -> str:
    payload = {
        "step_type": step_type,
        "input_artifact_ids": list(input_artifact_ids),
        "output_artifact_id": output_artifact_id,
        "target_artifact_id": target_artifact_id,
        "actor_id": actor_id,
        "method": method,
        "created_at": created_at.isoformat(),
    }
    return _sha256_hex(canonicalize(payload))
