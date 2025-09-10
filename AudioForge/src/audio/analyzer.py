import mimetypes
from typing import Dict, Set

from mutagen import File as MutagenFile

from src.config.constants import PRESERVE_SAMPLE_RATE


def _is_same_extension(input_ext: str, output_format: str) -> bool:
    return input_ext.lower() == output_format.lower()


def _create_audio_mime_to_extension_map() -> Dict[str, str]:
    """
    Create reverse mapping from MIME types to file extensions using a mimetypes library.
    Returns dictionary mapping 'audio/mpeg' -> 'mp3' etc.
    """
    if not mimetypes.inited:
        mimetypes.init()

    mime_to_ext = {}
    for ext, mime_type in mimetypes.types_map.items():
        if mime_type.startswith('audio/'):
            clean_ext = remove_leading_dot(ext)
            mime_to_ext[mime_type] = clean_ext

    return mime_to_ext


def get_supported_audio_formats() -> Set[str]:
    """
    Returns a list of supported audio format extensions.
    """
    mime_to_ext_map = _create_audio_mime_to_extension_map()
    formats = list(mime_to_ext_map.values())
    formats.sort()  # Sort alphabetically for a better presentation

    return set(formats)


def remove_leading_dot(ext: str) -> str:
    return ext[1:] if ext.startswith('.') else ext


def _get_audio_info_mutagen(file_path: str) -> tuple[None, int] | tuple[str, int]:
    """
    Get audio format and sample rate using a mutagen library with mimetypes reverse mapping.
    Returns (format_name, sample_rate) or (None, 0) if detection fails.
    """
    try:
        audio_file = MutagenFile(file_path)
        if audio_file is None:
            return None, 0

        # Get MIME type from mutagen
        mime_type = audio_file.mime[0] if audio_file.mime else ""

        format_name = _extract_format_from_mime_with_mimetypes(mime_type)

        sample_rate = getattr(audio_file.info, 'sample_rate', PRESERVE_SAMPLE_RATE)

        return format_name.lower(), int(sample_rate)
    except Exception:
        return None, 0


def _extract_format_from_mime_with_mimetypes(mime_type: str) -> str:
    """
    Extract format using mimetypes library reverse mapping.
    Fallback to subtype extraction if not found in mapping.
    """
    if not mime_type:
        return ""

    audio_mime_to_ext_map = _create_audio_mime_to_extension_map()

    if mime_type in audio_mime_to_ext_map:
        return audio_mime_to_ext_map[mime_type]

    return ""


def _sample_rate_conversion_needed(actual_rate: int, target_rate: int) -> bool:
    """Check if sample rate conversion is required."""
    if target_rate == PRESERVE_SAMPLE_RATE:
        return False
    return actual_rate != 0 and actual_rate != target_rate


def is_conversion_required(input_path: str, output_format: str, target_sample_rate: int) -> bool:
    """
    Check if conversion is needed using mutagen for fast audio analysis.
    """
    actual_format, actual_sample_rate = _get_audio_info_mutagen(input_path)

    if actual_format is None:
        return True

    if not _is_same_extension(actual_format, output_format):
        return True

    if _sample_rate_conversion_needed(actual_sample_rate, target_sample_rate):
        return True

    return False


def get_audio_duration(file_path: str) -> float:
    """
    Get audio duration in seconds using mutagen.
    Returns 0.0 if detection fails.
    """
    try:
        audio_file = MutagenFile(file_path)
        if audio_file is None:
            return 0.0

        duration = getattr(audio_file.info, 'length', 0.0)
        return float(duration)
    except Exception:
        return 0.0

