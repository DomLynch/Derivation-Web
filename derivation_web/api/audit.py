"""Per-request audit log.

Emits one structured-JSON line per request to stdout (uvicorn → journald).
Includes: ts, request_id, method, path, status, duration_ms, client_id,
key_id, and X-Forwarded-For when present (we sit behind nginx).

The auth dep stashes (client_id, key_id) on request.state. For unauthed
requests those stay absent. The middleware never logs the body or the
Authorization header — keys never reach the log stream.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

if TYPE_CHECKING:
    from starlette.requests import Request

_audit_log = logging.getLogger("derivation_web.audit")


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            _emit(request, request_id, 500, duration_ms, error=True)
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        _emit(request, request_id, status_code, duration_ms)
        return response


def _emit(
    request: Request,
    request_id: str,
    status_code: int,
    duration_ms: float,
    *,
    error: bool = False,
) -> None:
    state = request.state
    record = {
        "evt": "http",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status": status_code,
        "duration_ms": duration_ms,
        "client_id": getattr(state, "client_id", None),
        "key_id": getattr(state, "key_id", None),
        "xff": request.headers.get("x-forwarded-for"),
        "remote": request.client.host if request.client else None,
    }
    if error:
        record["error"] = True
    _audit_log.info(json.dumps(record, separators=(",", ":")))
