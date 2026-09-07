import pytest

from src.api.exception_handlers import UnsupportedFileTypeError
from src.api.mime_sniffer import sniff_mime
from tests.conftest import JPEG_MAGIC_BYTES, PDF_MAGIC_BYTES, PNG_MAGIC_BYTES


class TestSniffMime:
    @pytest.mark.parametrize(
        "data,expected",
        [
            (PNG_MAGIC_BYTES, "image/png"),
            (JPEG_MAGIC_BYTES, "image/jpeg"),
            (b"GIF87a" + b"\x00" * 10, "image/gif"),
            (b"GIF89a" + b"\x00" * 10, "image/gif"),
            (b"BM" + b"\x00" * 10, "image/bmp"),
            (b"II*\x00" + b"\x00" * 10, "image/tiff"),
            (b"MM\x00*" + b"\x00" * 10, "image/tiff"),
            (PDF_MAGIC_BYTES, "application/pdf"),
            (b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 10, "image/webp"),
        ],
    )
    def test_known_signatures(self, data: bytes, expected: str):
        # Then
        assert sniff_mime(data) == expected

    def test_unknown_signature_raises(self):
        # Then
        with pytest.raises(UnsupportedFileTypeError):
            sniff_mime(b"plain text content with no known magic prefix")

    def test_empty_bytes_raises(self):
        # Then
        with pytest.raises(UnsupportedFileTypeError):
            sniff_mime(b"")

    def test_riff_without_webp_tag_is_rejected(self):
        # Given a RIFF container that is not WEBP
        data = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 10

        # Then
        with pytest.raises(UnsupportedFileTypeError):
            sniff_mime(data)

    def test_short_riff_payload_is_rejected(self):
        # Then
        with pytest.raises(UnsupportedFileTypeError):
            sniff_mime(b"RIFF")
