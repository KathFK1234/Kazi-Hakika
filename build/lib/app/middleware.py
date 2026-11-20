"""Pure-ASGI middleware: security headers and the request body size cap."""

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                extra: list[tuple[bytes, bytes]] = [
                    (b"content-security-policy", CSP.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"x-frame-options", b"DENY"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if self.hsts:
                    extra.append(
                        (b"strict-transport-security", b"max-age=63072000; includeSubDomains")
                    )
                headers.extend((k, v) for k, v in extra if k not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class SameOriginMiddleware:
    """CSRF defence in depth for /api: state-changing requests must be JSON
    (a cross-site form can't send that without a CORS preflight, and CORS is
    closed) and, when the browser says where they came from, from our origin."""

    UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, app: ASGIApp, *, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in self.UNSAFE
            and scope["path"].startswith("/api/")
        ):
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            origin = headers.get(b"origin")
            if origin is not None and origin.decode("latin-1") not in self.allowed:
                await _reject(send, 403, b'{"detail":"Cross-origin request refused"}')
                return
            has_body = headers.get(b"content-length", b"0") != b"0" or (
                b"transfer-encoding" in headers
            )
            content_type = headers.get(b"content-type", b"").split(b";")[0].strip()
            if has_body and content_type != b"application/json":
                await _reject(send, 415, b'{"detail":"Send JSON (application/json)"}')
                return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """Rejects bodies over the cap, whether or not Content-Length is honest."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    await _reject(send, 400, b'{"detail":"Invalid Content-Length"}')
                    return
                if declared > self.max_bytes:
                    await _reject(send, 413, b'{"detail":"Request body too large"}')
                    return

        received = 0
        too_large = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    # Raised inside the endpoint's body read, so the app's own
                    # exception handling turns it into a clean 413.
                    raise HTTPException(status_code=413, detail="Request body too large")
            return message

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except HTTPException:
            if not (too_large and not response_started):
                raise
            await _reject(send, 413, b'{"detail":"Request body too large"}')


async def _reject(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
