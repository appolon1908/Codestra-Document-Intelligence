"""Image intake validation.

Images are decoded only far enough to learn their container type and pixel
dimensions from the header; no pixel data is decompressed here (the OCR
worker does that in its own sandbox). Raw bytes live only in request memory.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import struct
from dataclasses import dataclass

from .config import Settings

_B64_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
_DATA_URL_RE = re.compile(r"^data:image/[a-z0-9.+-]+;base64,", re.IGNORECASE)


class InvalidImage(ValueError):
    def __init__(self, side: str, code: str, message: str):
        super().__init__(message)
        self.side = side
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ValidatedImage:
    side: str
    media_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    content_base64: str  # normalised; transient, never persisted

    def descriptor(self) -> dict:
        """Metadata that is safe to persist."""
        return {
            "side": self.side,
            "media_type": self.media_type,
            "width": self.width,
            "height": self.height,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xD9:
            return None
        (seg_len,) = struct.unpack(">H", data[i + 2 : i + 4])
        if seg_len < 2:
            return None
        if marker in _SOF_MARKERS:
            if i + 9 > n:
                return None
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + seg_len
    return None


def decode_and_validate(side: str, payload: str, settings: Settings) -> ValidatedImage:
    if not isinstance(payload, str) or not payload:
        raise InvalidImage(side, "image_missing", f"{side} image is empty")
    payload = _DATA_URL_RE.sub("", payload.strip(), count=1)
    payload = "".join(payload.split())
    # Cheap pre-check before allocating decoded bytes: base64 inflates by 4/3.
    if len(payload) > (settings.max_image_bytes * 4) // 3 + 4:
        raise InvalidImage(side, "image_too_large", f"{side} image exceeds {settings.max_image_bytes} bytes")
    if len(payload) % 4 != 0 or not _B64_RE.match(payload):
        raise InvalidImage(side, "image_not_base64", f"{side} image is not valid base64")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidImage(side, "image_not_base64", f"{side} image is not valid base64") from exc
    if len(data) > settings.max_image_bytes:
        raise InvalidImage(side, "image_too_large", f"{side} image exceeds {settings.max_image_bytes} bytes")

    dims = _png_dimensions(data)
    media_type = "image/png"
    if dims is None:
        dims = _jpeg_dimensions(data)
        media_type = "image/jpeg"
    if dims is None:
        raise InvalidImage(side, "image_unsupported_format", f"{side} image must be a JPEG or PNG")
    width, height = dims
    if min(width, height) < settings.min_image_dimension:
        raise InvalidImage(
            side, "image_too_small", f"{side} image must be at least {settings.min_image_dimension}px per side"
        )
    if max(width, height) > settings.max_image_dimension or width * height > settings.max_image_pixels:
        raise InvalidImage(side, "image_dimensions_exceeded", f"{side} image dimensions exceed limits")

    return ValidatedImage(
        side=side,
        media_type=media_type,
        width=width,
        height=height,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        content_base64=payload,
    )
