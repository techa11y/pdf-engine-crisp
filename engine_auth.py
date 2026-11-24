"""Shared-secret check on every engine endpoint except the health route.

The endpoints split, build and merge PDFs, write the Supabase page queue and upload to the
public `pdf_outputs` bucket with the service key, and until 2026-11-24 they answered anyone
who knew the onrender.com address. The TechA11y callers (the worker on Render and the web
tier on Replit) now send the secret in the `x-pdf-engine-key` header; the engine compares it
in constant time and answers 401 when it is missing or wrong.

OFF while `PDF_ENGINE_SECRET` is unset or empty, so deploying this changes nothing. Turn it
on by setting the same value on the callers FIRST (a header the engine ignores is harmless),
then here. `/healthz` always stays open. Same file in pdf-enginev2 and pdf-engine-crisp.
"""
import hmac
import logging
import os

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

ENGINE_SECRET_ENV = "PDF_ENGINE_SECRET"
ENGINE_KEY_HEADER = "x-pdf-engine-key"
OPEN_PATHS = frozenset({"/healthz"})

logger = logging.getLogger(__name__)


def engine_secret() -> str:
    """The configured secret, read per request ("" = the check is off)."""
    return (os.getenv(ENGINE_SECRET_ENV) or "").strip()


def key_is_valid(provided, secret: str) -> bool:
    """Constant-time compare of the sent key with the secret (bytes, so any header text is safe)."""
    return hmac.compare_digest((provided or "").encode("utf-8"), secret.encode("utf-8"))


class EngineKeyMiddleware:
    """Plain ASGI middleware: refuses before the endpoint runs (and before a multipart body
    is parsed); passes requests and responses through untouched otherwise."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        secret = engine_secret()
        if not secret or scope.get("path") in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        if key_is_valid(Headers(scope=scope).get(ENGINE_KEY_HEADER), secret):
            await self.app(scope, receive, send)
            return
        logger.warning(
            "[AUTH] refused %s %s: missing or wrong %s header",
            scope.get("method"), scope.get("path"), ENGINE_KEY_HEADER,
        )
        await JSONResponse(status_code=401, content={"error": "unauthorized"})(scope, receive, send)
