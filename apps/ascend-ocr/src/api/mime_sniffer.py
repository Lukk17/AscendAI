from src.api.exception_handlers import UnsupportedFileTypeError

_PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE: bytes = b"\xff\xd8\xff"
_GIF87A_SIGNATURE: bytes = b"GIF87a"
_GIF89A_SIGNATURE: bytes = b"GIF89a"
_BMP_SIGNATURE: bytes = b"BM"
_TIFF_LE_SIGNATURE: bytes = b"II*\x00"
_TIFF_BE_SIGNATURE: bytes = b"MM\x00*"
_PDF_SIGNATURE: bytes = b"%PDF-"
_WEBP_RIFF_PREFIX: bytes = b"RIFF"
_WEBP_TAG: bytes = b"WEBP"
_WEBP_HEADER_MIN_LENGTH: int = 12

_PREFIX_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (_PNG_SIGNATURE, "image/png"),
    (_JPEG_SIGNATURE, "image/jpeg"),
    (_GIF87A_SIGNATURE, "image/gif"),
    (_GIF89A_SIGNATURE, "image/gif"),
    (_BMP_SIGNATURE, "image/bmp"),
    (_TIFF_LE_SIGNATURE, "image/tiff"),
    (_TIFF_BE_SIGNATURE, "image/tiff"),
    (_PDF_SIGNATURE, "application/pdf"),
)


def sniff_mime(data: bytes) -> str:
    """Return the canonical MIME type of `data` based on its magic bytes.

    Raises UnsupportedFileTypeError when no allowed signature matches.
    """
    for prefix, mime in _PREFIX_SIGNATURES:
        if data.startswith(prefix):
            return mime

    if (
        len(data) >= _WEBP_HEADER_MIN_LENGTH
        and data.startswith(_WEBP_RIFF_PREFIX)
        and data[8:_WEBP_HEADER_MIN_LENGTH] == _WEBP_TAG
    ):
        return "image/webp"

    raise UnsupportedFileTypeError("Unrecognised file signature")
