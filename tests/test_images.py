import pytest

from app.images import InvalidImage, decode_and_validate

from .conftest import b64, make_jpeg, make_png, make_settings


def test_png_and_jpeg_dimensions():
    s = make_settings()
    png = decode_and_validate("front", b64(make_png(1024, 768)), s)
    assert (png.media_type, png.width, png.height) == ("image/png", 1024, 768)
    jpg = decode_and_validate("back", b64(make_jpeg(640, 480)), s)
    assert (jpg.media_type, jpg.width, jpg.height) == ("image/jpeg", 640, 480)
    assert "content_base64" not in jpg.descriptor()


def test_oversized_base64_rejected_before_decode():
    s = make_settings(MAX_IMAGE_BYTES="1000")
    with pytest.raises(InvalidImage) as exc:
        decode_and_validate("front", "A" * 5000, s)
    assert exc.value.code == "image_too_large"


def test_truncated_jpeg():
    with pytest.raises(InvalidImage):
        decode_and_validate("front", b64(make_jpeg()[:10]), make_settings())
