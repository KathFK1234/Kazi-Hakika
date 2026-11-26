from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

INDEX = (
    "<!doctype html><html><head><title>__APP_NAME__</title>"
    '<meta name="description" content="__APP_NAME__: __APP_TAGLINE__"></head>'
    '<body><div id="root"></div></body></html>'
)


@pytest.fixture
def site(tmp_path: Path) -> TestClient:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX)
    (static / "assets" / "app.js").write_text("console.log('hi')")
    (static / "theme.js").write_text("// theme")
    (tmp_path / "secret.txt").write_text("outside the static dir")
    settings = make_settings(app_name='Kazi "<Hakika>"', app_tagline="tag & line")
    return TestClient(create_app(settings, static_dir=static))


def test_index_gets_the_escaped_name(site: TestClient) -> None:
    r = site.get("/")
    assert r.status_code == 200
    assert "<title>Kazi &quot;&lt;Hakika&gt;&quot;</title>" in r.text
    assert "tag &amp; line" in r.text
    assert "__APP_NAME__" not in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert "default-src 'self'" in r.headers["content-security-policy"]


@pytest.mark.parametrize("path", ["/applications/new", "/settings", "/verify-email"])
def test_client_routes_get_index(site: TestClient, path: str) -> None:
    assert '<div id="root">' in site.get(path).text


def test_assets_and_head(site: TestClient) -> None:
    assert site.get("/assets/app.js").text == "console.log('hi')"
    assert site.head("/").status_code == 200
    assert site.head("/settings").status_code == 200


@pytest.mark.parametrize("path", ["/../secret.txt", "/..%2Fsecret.txt", "/assets/../../secret.txt"])
def test_no_escape_from_the_static_dir(site: TestClient, path: str) -> None:
    assert "outside the static dir" not in site.get(path).text


@pytest.mark.parametrize("path", ["/api", "/api/unknown", "/mcp"])
def test_api_paths_never_fall_back_to_index(site: TestClient, path: str) -> None:
    r = site.get(path)
    assert r.status_code == 404
    assert "root" not in r.text


def test_without_a_build_pages_are_404(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(), static_dir=tmp_path / "missing"))
    assert client.get("/").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}


def test_hashed_assets_are_cached_for_a_year(site: TestClient) -> None:
    r = site.get("/assets/app.js")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    missing = site.get("/assets/nope.js")
    assert missing.status_code == 404
    assert "immutable" not in missing.headers.get("cache-control", "")


def test_unhashed_root_files_are_revalidated(site: TestClient) -> None:
    r = site.get("/theme.js")
    assert r.status_code == 200
    assert r.text == "// theme"
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-cache"
