import io

from PIL import Image

from scripts.render_images import render_document

TEXT = "FORM I & XIV (SYNTHETIC)\nOccupant: Asha Naik\nSurvey No.: 123/4\n"


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_rendering_is_deterministic():
    assert _png(render_document(TEXT, "clean")) == _png(render_document(TEXT, "clean"))
    assert _png(render_document(TEXT, "degraded")) == _png(render_document(TEXT, "degraded"))


def test_degraded_differs_from_clean_and_has_lower_contrast():
    clean, degraded = render_document(TEXT, "clean"), render_document(TEXT, "degraded")
    assert clean.size == degraded.size
    lo_c, hi_c = clean.convert("L").getextrema()
    lo_d, hi_d = degraded.convert("L").getextrema()
    assert (hi_d - lo_d) < (hi_c - lo_c)


def test_clean_render_is_black_text_on_white():
    lo, hi = render_document(TEXT, "clean").convert("L").getextrema()
    assert lo < 40 and hi > 240
