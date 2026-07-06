"""Per-route rate limiting — Sprint 5.3 (Performance & Reliability).

Wraps `slowapi` with a single shared :data:`limiter` instance and a set of
named limit strings so route modules stay consistent instead of scattering
magic numbers.

Limits (per client IP):
  * POST create/submit endpoints .......... 30 / minute   (:data:`POST_LIMIT`)
  * GET list/query endpoints ............... 120 / minute  (:data:`GET_LIMIT`)
  * Auth endpoints (login) ................. 10 / minute   (:data:`AUTH_LIMIT`)
  * Agent dispatch (POST /v1/requests) ..... 20 / minute   (:data:`DISPATCH_LIMIT`)

Usage in a route module::

    from app.rate_limit import limiter, POST_LIMIT
    from fastapi import Request

    @router.post("")
    @limiter.limit(POST_LIMIT)
    async def create(request: Request, ...):
        ...

The decorated endpoint **must** accept a ``request: Request`` parameter —
slowapi resolves the client key from it. See :func:`register_rate_limiting`
for wiring the middleware + 429 handler into the app.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

log = logging.getLogger("quill.rate_limit")

# Single shared limiter. key_func = client IP (honours X-Forwarded-For via
# get_remote_address when the app runs behind a trusted proxy). In-memory
# storage is fine for a single-process deployment; swap `storage_uri` for
# redis:// if we scale horizontally.
#
# headers_enabled is left OFF: with it on, the decorator's success path tries
# to inject X-RateLimit-* into a `response` kwarg the endpoints don't declare
# and raises. SlowAPIMiddleware + our 429 handler attach the headers instead.
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Named limits — reference these from route modules, don't inline the strings.
# ---------------------------------------------------------------------------
POST_LIMIT = "30/minute"       # create / submit
GET_LIMIT = "120/minute"       # list / query
AUTH_LIMIT = "10/minute"       # login — stricter, brute-force resistance
DISPATCH_LIMIT = "20/minute"   # agent dispatch (POST /v1/requests)


def _retry_after_seconds(exc: RateLimitExceeded) -> int:
    """Seconds until the tripped limit's window resets.

    Uses the window size of the exceeded limit (all our limits are per-minute,
    so this is 60). Falls back to 60 if slowapi's internal shape shifts.
    """
    try:
        return max(1, int(exc.limit.limit.get_expiry()))  # RateLimitItem.get_expiry()
    except Exception:  # noqa: BLE001 — never let header math break the 429
        return 60


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 handler that matches the app's ``{"detail": ...}`` error envelope."""
    retry_after = _retry_after_seconds(exc)
    rid = getattr(request.state, "request_id", None)
    log.warning(
        "rate_limit.exceeded path=%s ip=%s limit=%s retry_after=%s request_id=%s",
        request.url.path,
        get_remote_address(request),
        getattr(exc, "detail", ""),
        retry_after,
        rid,
    )
    content = {
        "detail": f"Rate limit exceeded. Try again in {retry_after} seconds."
    }
    response = JSONResponse(status_code=429, content=content)
    response.headers["Retry-After"] = str(retry_after)
    if rid is not None:
        response.headers["x-request-id"] = rid
    return response


def register_rate_limiting(app) -> None:
    """Attach the limiter, its middleware, and the 429 handler to ``app``.

    Call once during app construction in ``main.py``.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
