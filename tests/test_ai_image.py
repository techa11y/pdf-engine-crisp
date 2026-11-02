#!/usr/bin/env python3
"""Regression test for ai_image: LLM page images are sized to a visual-token budget.

Run with:  python tests/test_ai_image.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import pymupdf as mupdf
except ImportError:
    import fitz as mupdf
from PIL import Image

from ai_image import (DEFAULT_MAX_TOKENS, fit_dimensions, render_ai_image,  # noqa: E402
                      visual_tokens)

PT = 72.0


def _page(w_in, h_in):
    doc = mupdf.open()
    p = doc.new_page(width=w_in * PT, height=h_in * PT)
    for y in range(40, int(h_in * PT) - 20, 18):
        p.insert_text((36, y), "Sample body text line for the AI page image " * 2, fontsize=10)
    return doc, p


def _dims(jpeg_bytes):
    return Image.open(io.BytesIO(jpeg_bytes)).size


def test_token_formula_matches_docs_example():
    assert visual_tokens(1075, 1520) == 39 * 55 == 2145
    print("ok: token formula reproduces the documented 1075x1520 -> 2145 example")


def test_fit_is_largest_size_within_budget():
    for w, h in [(1275, 1650), (1075, 1520), (3300, 5100), (8250, 13750), (1600, 1600)]:
        tw, th = fit_dimensions(w, h, DEFAULT_MAX_TOKENS)
        assert tw <= w and th <= h
        assert visual_tokens(tw, th) <= DEFAULT_MAX_TOKENS, (w, h, tw, th)
        assert visual_tokens(tw * 1.04, th * 1.04) > DEFAULT_MAX_TOKENS, "not the largest fitting size"
        assert abs(tw / th - w / h) < 0.02, "aspect ratio must be preserved"
    print("ok: fit_dimensions returns the largest aspect-preserving size within 1568 tokens")


def test_small_images_are_not_upscaled_or_changed():
    assert fit_dimensions(816, 1056, DEFAULT_MAX_TOKENS) == (816, 1056)   # Letter @ 96 DPI = 1140 tokens
    assert fit_dimensions(816, 1056, 0) == (816, 1056)                    # budget 0 disables
    print("ok: images already within budget are untouched; budget 0 disables the cap")


def test_render_letter_page_respects_budget():
    doc, page = _page(8.5, 11)
    data = render_ai_image(page, 150, budget=DEFAULT_MAX_TOKENS, quality=80)
    w, h = _dims(data)
    assert visual_tokens(w, h) <= DEFAULT_MAX_TOKENS, (w, h)
    assert w < 1275 and h < 1650, "150 DPI Letter (2714 tokens) must be reduced"
    native = render_ai_image(page, 150, budget=0, quality=80)
    nw, nh = _dims(native)
    assert (nw, nh) == (1275, 1650), (nw, nh)
    assert len(data) < len(native)
    print(f"ok: Letter @150 DPI -> {w}x{h} ({visual_tokens(w, h)} tokens, {len(data)//1024} KB vs native {len(native)//1024} KB)")


def test_render_poster_is_bounded():
    doc, page = _page(33, 55)
    data = render_ai_image(page, 150, budget=DEFAULT_MAX_TOKENS, quality=80)
    w, h = _dims(data)
    assert visual_tokens(w, h) <= DEFAULT_MAX_TOKENS
    assert len(data) < 600 * 1024
    print(f"ok: 33x55 in poster -> {w}x{h} ({visual_tokens(w, h)} tokens, {len(data)//1024} KB)")


def test_env_overrides():
    doc, page = _page(8.5, 11)
    os.environ["PDF_AI_IMAGE_MAX_TOKENS"] = "4784"
    os.environ["PDF_AI_IMAGE_JPEG_QUALITY"] = "60"
    try:
        w, h = _dims(render_ai_image(page, 150))
        assert (w, h) == (1275, 1650), "2714 tokens fits a 4784 budget"
    finally:
        del os.environ["PDF_AI_IMAGE_MAX_TOKENS"]
        del os.environ["PDF_AI_IMAGE_JPEG_QUALITY"]
    print("ok: PDF_AI_IMAGE_MAX_TOKENS / PDF_AI_IMAGE_JPEG_QUALITY overrides apply")


if __name__ == "__main__":
    test_token_formula_matches_docs_example()
    test_fit_is_largest_size_within_budget()
    test_small_images_are_not_upscaled_or_changed()
    test_render_letter_page_respects_budget()
    test_render_poster_is_bounded()
    test_env_overrides()
    print("\nALL ai_image tests passed")
