"""API-key transport auth for write endpoints.

Separate concern from Ed25519 step signatures:
- API key answers "who is allowed to call DW" (transport).
- Signature answers "who produced and stands behind this step" (provenance).

Keys are 256-bit url-safe random with a `dwk_` prefix for visual identification.
We store SHA-256 hashes only; raw keys are shown once at issuance and never
recoverable. Lookup is via indexed equality on `key_hash` — sha256 is itself
constant-time and the DB lookup leaks no per-byte timing.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from derivation_web.db import repo
from derivation_web.db.session import get_session

KEY_PREFIX = "dwk_"
_KEY_BYTES = 32  # 256 bits of entropy
# Hard cap on accepted key length: prevents DoS via giant strings (sha256
# over 10MB ≈ 25 ms per request). Real keys are ~47 chars.
MAX_KEY_LEN = 128


def generate_key() -> tuple[str, str]:
    """Return (raw_key, key_hash). Raw is shown once and never persisted."""
    raw = KEY_PREFIX + secrets.token_urlsafe(_KEY_BYTES)
    return raw, hash_key(raw)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        candidate = x_api_key.strip()
        return candidate or None
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1] or None
    return None


def _looks_like_dw_key(key: str) -> bool:
    """Cheap pre-check before hashing. Same 401 message either way."""
    return (
        key.startswith(KEY_PREFIX)
        and len(key) <= MAX_KEY_LEN
        and len(key) >= len(KEY_PREFIX) + 1
    )


def require_api_key(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    """FastAPI dependency. Returns client_id of the validated key.

    Raises 401 if header is missing, malformed, unknown, or revoked. The
    same message is used for malformed and unknown to avoid an oracle.
    Stashes (client_id, key_id) on request.state for the audit middleware.
    """
    key = _extract_key(authorization, x_api_key)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing API key (use Authorization: Bearer <key> or X-API-Key)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not _looks_like_dw_key(key):
        # Reject without DB hit. Defends against unbounded-input DoS.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or revoked API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    record = repo.find_active_api_key_by_hash(session, hash_key(key))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or revoked API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.client_id = record.client_id
    request.state.key_id = record.id
    return record.client_id
