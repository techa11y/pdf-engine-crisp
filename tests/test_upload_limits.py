#!/usr/bin/env python3
"""Regression test: the MAX_PDF_UPLOAD_MB override in main.py must lift Starlette's
default 1 MiB cap on NON-file multipart parts (Starlette >= 0.41), otherwise a large
`html_content` form field on /build is rejected with 400 "Part exceeded maximum size".

Run with:  python tests/test_upload_limits.py
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

# main.py imports commonforms (heavy ML deps). The override under test does not need
# it, so stub the module if it is not installed in the test environment.
try:
    import commonforms  # noqa: F401
except ImportError:
    stub = types.ModuleType("commonforms")
    stub.prepare_form = lambda *a, **k: None
    sys.modules["commonforms"] = stub

from fastapi import FastAPI, Form
from fastapi.testclient import TestClient
import starlette

TWO_MIB = 2 * 1024 * 1024


def _post_big_field(app):
    @app.post("/f")
    async def f(html_content: str = Form(...)):
        return {"n": len(html_content)}
    # `files=` forces multipart/form-data encoding, exactly as the worker sends /build.
    return TestClient(app, raise_server_exceptions=False).post(
        "/f", data={"html_content": "x" * TWO_MIB}, files={"dummy": ("d.txt", b"x", "text/plain")}
    )


def test_control_starlette_default_cap_still_exists():
    """Sanity: if Starlette ever drops the cap, this test stops proving anything."""
    import starlette.formparsers as fp
    assert hasattr(fp.MultiPartParser, "max_part_size"), "Starlette changed its multipart API"
    print("ok: Starlette", starlette.__version__, "exposes MultiPartParser.max_part_size")


def test_override_lifts_cap_for_large_form_field():
    import main  # installs the override on import
    assert main._MAX_UPLOAD_BYTES >= TWO_MIB
    r = _post_big_field(FastAPI())
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["n"] == TWO_MIB
    print("ok: 2 MiB non-file part accepted with override ->", r.status_code)


def test_override_value_tracks_env():
    import main
    assert main._MAX_UPLOAD_BYTES == main.MAX_PDF_UPLOAD_MB * 1024 * 1024
    import starlette.formparsers as fp
    assert fp.MultiPartParser.max_part_size == main._MAX_UPLOAD_BYTES
    print("ok: MultiPartParser.max_part_size ==", main.MAX_PDF_UPLOAD_MB, "MB")


if __name__ == "__main__":
    test_control_starlette_default_cap_still_exists()
    test_override_lifts_cap_for_large_form_field()
    test_override_value_tracks_env()
    print("\nALL upload_limits tests passed")
