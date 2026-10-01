"""Generate the three low-resolution copies of the flat straightening photo.

Each copy is `straightening-photo-flat.jpg` shrunk with LANCZOS to a long side of 1600, 1000 or 640 pixels with its
aspect ratio kept, saved as JPEG at quality 85, 80 or 75, and stripped of every APP0 to APP15 segment and every
comment, so it carries no EXIF, ICC, XMP or JFIF data.
"""

import io
import struct
from pathlib import Path

from PIL import Image

OUTPUT_DIR = Path(__file__).resolve().parent
SOURCE = OUTPUT_DIR / "straightening-photo-flat.jpg"
VARIANTS = ((1600, 85), (1000, 80), (640, 75))

MARKER_PREFIX = 0xFF
START_OF_IMAGE = b"\xff\xd8"
END_OF_IMAGE = b"\xff\xd9"
START_OF_SCAN = 0xDA
FIRST_APP_MARKER = 0xE0
LAST_APP_MARKER = 0xEF
COMMENT_MARKER = 0xFE


def is_stripped(marker: int) -> bool:
    return FIRST_APP_MARKER <= marker <= LAST_APP_MARKER or marker == COMMENT_MARKER


def strip_segments(data: bytes) -> bytes:
    if data[:2] != START_OF_IMAGE:
        raise RuntimeError("encoded image does not start with a JPEG start of image marker")

    output = bytearray(START_OF_IMAGE)
    offset = 2
    while True:
        if data[offset] != MARKER_PREFIX:
            raise RuntimeError(f"expected a segment marker at offset {offset}")

        marker = data[offset + 1]
        if marker == START_OF_SCAN:
            end = data.rindex(END_OF_IMAGE) + len(END_OF_IMAGE)
            output += data[offset:end]
            return bytes(output)

        length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if not is_stripped(marker):
            output += data[offset : offset + 2 + length]
        offset += 2 + length


def downscale(source: Image.Image, long_side: int, quality: int) -> bytes:
    width, height = source.size
    scale = long_side / max(width, height)
    size = (round(width * scale), round(height * scale))
    image = source.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return strip_segments(buffer.getvalue())


with Image.open(SOURCE) as source:
    for long_side, quality in VARIANTS:
        output = OUTPUT_DIR / f"straightening-photo-flat-{long_side}px.jpg"
        output.write_bytes(downscale(source, long_side, quality))
        print(output, output.stat().st_size, "bytes")
