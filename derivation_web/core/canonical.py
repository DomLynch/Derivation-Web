"""Deterministic JSON serialization for hashing.

v1 uses sorted-key JSON (no whitespace, UTF-8). RFC 8785 adoption is
deferred until a non-Python client consumes the ledger — see DECISIONS.md.
"""

from __future__ import annotations

import json
from typing import Any


def canonicalize(obj: Any) -> bytes:
    """Serialize to deterministic UTF-8 JSON bytes."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
