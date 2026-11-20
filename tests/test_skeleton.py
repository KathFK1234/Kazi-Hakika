from collections.abc import Iterator

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def make_client(**overrides: object) -> TestClient:
    return TestClient(create_app(make_settings(**overrides)))


def test_health_ok() -> None:
    response = make_client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_security_headers_present() -> None:
    response = make_client().get("/health")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in response.headers


def test_hsts_only_in_production() -> None:
    client = make_client(
        environment="production", secret_key="x" * 40, base_url="https://kazi.example"
    )
    assert "max-age=" in client.get("/health").headers["strict-transport-security"]


def test_production_rejects_default_secret() -> None:
    import pytest

    with pytest.raises(ValueError, match="SECRET_KEY"):
        make_settings(environment="production", base_url="https://kazi.example")


def test_body_over_64kb_rejected() -> None:
    response = make_client().post("/health", content=b"x" * (64 * 1024 + 1))
    assert response.status_code == 413


def test_body_over_cap_without_content_length_rejected() -> None:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from app.middleware import BodySizeLimitMiddleware

    async def echo(request: Request) -> PlainTextResponse:
        return PlainTextResponse(str(len(await request.body())))

    inner = Starlette(routes=[Route("/echo", echo, methods=["POST"])])
    client = TestClient(BodySizeLimitMiddleware(inner, max_bytes=64 * 1024))

    def chunks() -> Iterator[bytes]:
        for _ in range(70):
            yield b"x" * 1024

    assert client.post("/echo", content=chunks()).status_code == 413
    assert client.post("/echo", content=b"x" * 100).text == "100"


def test_unknown_api_path_is_404_not_spa() -> None:
    assert make_client().get("/api/nope").status_code == 404


def test_docs_hidden_in_production() -> None:
    client = make_client(
        environment="production", secret_key="x" * 40, base_url="https://kazi.example"
    )
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def test_meta_uses_settings() -> None:
    client = make_client(app_name="Test Kazi", app_tagline="a tagline")
    assert client.get("/api/meta").json() == {"name": "Test Kazi", "tagline": "a tagline"}


def test_spa_path_traversal_blocked() -> None:
    response = make_client().get("/..%2F..%2Fconfig.py")
    assert "BaseSettings" not in response.text
