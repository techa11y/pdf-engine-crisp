#!/usr/bin/env python3
"""Regression test for raster_budget.capped_dpi (OOM on large-format pages).

Run with:  python tests/test_raster_cap.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from raster_budget import capped_dpi, DEFAULT_MAX_PIXELS, MIN_DPI  # noqa: E402

PT = 72.0


def _pixels(w_in, h_in, dpi):
    return w_in * dpi * h_in * dpi


def test_ordinary_pages_unchanged():
    for (w, h) in [(8.5, 11), (11, 17), (8.27, 11.69), (17, 11)]:
        for dpi in (96, 120, 150, 250):
            assert capped_dpi(w * PT, h * PT, dpi) == dpi, (w, h, dpi)
    print("ok: Letter/Tabloid/A4 keep their requested DPI at 96-250")


def test_poster_is_capped_within_budget():
    d = capped_dpi(33 * PT, 55 * PT, 250)
    assert d < 250 and d >= MIN_DPI, d
    assert _pixels(33, 55, d) <= DEFAULT_MAX_PIXELS, (d, _pixels(33, 55, d))
    assert _pixels(33, 55, d + 1) > DEFAULT_MAX_PIXELS, "cap should pick the largest fitting DPI"
    print(f"ok: 33x55 in poster at 250 DPI capped to {d} DPI ({_pixels(33, 55, d) / 1e6:.1f} MP)")


def test_24x36_only_slightly_reduced():
    d = capped_dpi(24 * PT, 36 * PT, 250)
    assert 150 <= d < 250, d
    print(f"ok: 24x36 in poster at 250 DPI -> {d} DPI")


def test_floor_and_disable():
    assert capped_dpi(400 * PT, 400 * PT, 250) == MIN_DPI
    assert capped_dpi(33 * PT, 55 * PT, 250, max_px=0) == 250
    assert capped_dpi(33 * PT, 55 * PT, 250, max_px=-1) == 250
    print("ok: MIN_DPI floor holds; max_px <= 0 disables the cap")


def test_env_override():
    os.environ["PDF_VISUAL_MAX_PIXELS"] = "120000000"
    try:
        assert capped_dpi(33 * PT, 55 * PT, 250) == 250, "113 MP fits a 120 MP budget"
        os.environ["PDF_VISUAL_MAX_PIXELS"] = "not-a-number"
        assert capped_dpi(33 * PT, 55 * PT, 250) < 250, "bad env falls back to the default budget"
    finally:
        del os.environ["PDF_VISUAL_MAX_PIXELS"]
    print("ok: PDF_VISUAL_MAX_PIXELS override and fallback")


if __name__ == "__main__":
    test_ordinary_pages_unchanged()
    test_poster_is_capped_within_budget()
    test_24x36_only_slightly_reduced()
    test_floor_and_disable()
    test_env_override()
    print("\nALL raster_cap tests passed")
