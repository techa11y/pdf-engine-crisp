#!/usr/bin/env python3
"""Shared-secret check (engine_auth.py): with PDF_ENGINE_SECRET unset every endpoint is open
as before; with it set every endpoint except /healthz needs the same value in the
x-pdf-engine-key header (401 otherwise, before the endpoint runs).

Run with:  python tests/test_engine_auth.py
"""
import logging
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
for k in ("SUPABASE_URL", "SUPABASE_KEY", "PDF_ENGINE_SECRET"):
    os.environ.pop(k, None)
try:
    import commonforms  # noqa: F401
except ImportError:  # heavy ML dependency not needed for this test
    stub = types.ModuleType("commonforms")
    stub.prepare_form = lambda *a, **k: None
    sys.modules["commonforms"] = stub
logging.disable(logging.CRITICAL)

try:
    import pymupdf as mupdf
except ImportError:
    import fitz as mupdf
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import main

client = TestClient(main.app, raise_server_exceptions=False)
SECRET = "test-engine-secret-7f3c"
HEADER = "x-pdf-engine-key"
# Every engine endpoint the callers use, plus the legacy ones; a new route must be added here.
EXPECTED_ROUTES = {
    "/get-page-count", "/detect-forms", "/detect-forms-single", "/split-to-queue",
    "/build", "/split",
}


def _pdf():
    d = mupdf.open()
    d.new_page(width=612, height=792)
    return d.tobytes()


def _page_count(headers=None):
    return client.post("/get-page-count", files={"file": ("a.pdf", _pdf(), "application/pdf")}, headers=headers or {})


class _secret:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        os.environ["PDF_ENGINE_SECRET"] = self.value

    def __exit__(self, *exc):
        os.environ.pop("PDF_ENGINE_SECRET", None)


def test_route_list_is_known():
    routes = {r.path for r in main.app.routes if isinstance(r, APIRoute) and r.path != "/healthz"}
    assert routes == EXPECTED_ROUTES, routes
    print("ok: the protected endpoints are", sorted(routes))


def test_unset_is_open():
    r = _page_count()
    assert r.status_code == 200 and r.json() == {"total_pages": 1}, (r.status_code, r.text)
    with _secret("   "):  # blank counts as unset
        r = _page_count()
    assert r.status_code == 200, (r.status_code, r.text)
    print("ok: PDF_ENGINE_SECRET unset or blank -> open, no header needed")


def test_set_refuses_missing_and_wrong_key_on_every_endpoint():
    wrong = [None, "", "wrong", SECRET[:-1], SECRET + "x", SECRET.upper(), " " + SECRET + "x"]
    with _secret(SECRET):
        for path in sorted(EXPECTED_ROUTES) + ["/openapi.json"]:
            for key in wrong:
                headers = {} if key is None else {HEADER: key}
                method = client.get if path == "/openapi.json" else client.post
                r = method(path, headers=headers)
                assert r.status_code == 401, (path, key, r.status_code, r.text)
                assert r.json() == {"error": "unauthorized"}, (path, r.text)
        # A big upload is refused too, before the endpoint reads it.
        r = _page_count({HEADER: "wrong"})
        assert r.status_code == 401, (r.status_code, r.text)
    print("ok: secret set -> missing / wrong / near-miss key refused with 401 on all", len(EXPECTED_ROUTES), "endpoints")


def test_set_right_key_accepted():
    with _secret(SECRET):
        r = _page_count({HEADER: SECRET})
        assert r.status_code == 200 and r.json() == {"total_pages": 1}, (r.status_code, r.text)
        r = _page_count({"X-PDF-Engine-Key": SECRET})  # header names are case-insensitive
        assert r.status_code == 200, (r.status_code, r.text)
        r = client.post("/build", headers={HEADER: SECRET})
        assert r.status_code == 422 and "html_content" in r.text, (r.status_code, r.text)  # reached the endpoint
    with _secret("  " + SECRET + "\n"):  # the env value is trimmed
        r = _page_count({HEADER: SECRET})
        assert r.status_code == 200, (r.status_code, r.text)
    print("ok: secret set -> the right key reaches the endpoints")


def test_health_stays_open():
    with _secret(SECRET):
        r = client.get("/healthz")
        assert r.status_code == 200 and r.json()["status"] == "online", (r.status_code, r.text)
        r = client.get("/healthz", headers={HEADER: "wrong"})
        assert r.status_code == 200, (r.status_code, r.text)
    print("ok: /healthz answers without the key")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} engine_auth tests passed")
