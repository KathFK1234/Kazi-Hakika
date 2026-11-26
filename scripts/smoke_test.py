"""Post-deploy smoke test: python scripts/smoke_test.py https://<app>.up.railway.app

Signs up a throwaway account, signs in, adds an application due tomorrow,
checks it appears in the digest preview, then deletes the account. Uses one
sign-up email from the day's budget (the confirmation link goes unused).
Exits non-zero at the first failed step.
"""

import re
import secrets
import sys
from datetime import date, timedelta

import httpx


def check(condition: bool, step: str) -> None:
    if not condition:
        print(f"FAIL: {step}")
        sys.exit(1)
    print(f"ok   {step}")


def main(base_url: str) -> None:
    handle = f"smoke-{secrets.token_hex(4)}"
    email = f"{handle}@example.com"
    password = secrets.token_urlsafe(18)
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=15, follow_redirects=False) as c:
        r = c.get("/health")
        check(r.status_code == 200 and r.json() == {"status": "ok"}, "health")

        page = c.get("/")
        check(page.status_code == 200 and '<div id="root">' in page.text, "web app served")
        headers = page.headers
        check("default-src 'self'" in headers.get("content-security-policy", ""), "CSP header")
        if base_url.startswith("https://"):
            check("max-age" in headers.get("strict-transport-security", ""), "HSTS header")

        check('<script src="/theme.js"></script>' in page.text, "page loads the theme script")
        r = c.get("/theme.js")
        check(
            r.status_code == 200 and "javascript" in r.headers.get("content-type", ""),
            "theme script served as JavaScript",
        )
        found = re.search(r'src="(/assets/[^"]+\.js)"', page.text)
        bundle = found.group(1) if found else ""
        check(bool(bundle), "page references a bundled script")
        r = c.get(bundle)
        check(
            r.status_code == 200 and "immutable" in r.headers.get("cache-control", ""),
            "bundled assets cached as immutable",
        )

        r = c.post(
            "/api/auth/signup", json={"email": email, "password": password, "handle": handle}
        )
        check(r.status_code == 202, f"sign up ({r.status_code})")

        r = c.post("/api/auth/login", json={"email": email, "password": password})
        check(r.status_code == 200, f"sign in ({r.status_code})")
        me = c.get("/api/auth/me").json()
        check(me["handle"] == handle, "session works")
        c.headers["X-CSRF-Token"] = me["csrf_token"]

        try:
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            r = c.post(
                "/api/applications",
                json={
                    "role_title": "Smoke test role",
                    "company_name": "Smoke",
                    "deadline": tomorrow,
                },
            )
            check(r.status_code == 201, f"add application ({r.status_code})")

            preview = c.get("/api/account/digest-preview").json()
            titles = [item["role_title"] for item in preview["items"]]
            check("Smoke test role" in titles, "application shows in the digest preview")

            other = c.get("/api/applications/00000000-0000-0000-0000-000000000000")
            check(other.status_code == 404, "unknown application is 404")
        finally:
            r = c.request("DELETE", "/api/account", json={"confirm_handle": handle})
            check(r.status_code == 204, f"delete the smoke account ({r.status_code})")
        check(c.get("/api/auth/me").status_code == 401, "signed out after deletion")
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        main(sys.argv[1])
    except httpx.HTTPError as exc:
        print(f"FAIL: could not reach the site ({type(exc).__name__}: {exc})")
        sys.exit(1)
