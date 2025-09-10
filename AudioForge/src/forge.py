from __future__ import annotations

import logging
import subprocess
from typing import List

from src.audio.analyzer import is_conversion_required
from src.constants import DEFAULT_FORMAT, WAVE_FORMAT, PRESERVE_SAMPLE_RATE, DEFAULT_SILENCE_DURATION, \
    DEFAULT_SILENCE_THRESHOLD
from src.error.forge_error import ForgeError
from src.io.file_service import create_temp_path, ensure_parent_dir, get_file_extension, print_file_info

logger = logging.getLogger(__name__)


def _run_command(command: List[str]) -> None:
    """
    Run a shell command and raise ForgeError with stderr details on failure.
    """
    logger.info(f"Executing command: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)

    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(command)}")
        logger.error(f"Error output: {e.stderr.strip()}")

        raise ForgeError(f"Command `{command[0]}` failed: {e.stderr.strip() or e.stdout.strip()}") \
            from e


def _ffmpeg_convert_cmd(input_path: str, sample_rate: int, output_path: str) -> List[str]:
    """
    Build an FFmpeg command that converts sample rate and format inferred from output_path.
    FFmpeg will CREATE a new file at output_path (overwrites if exists due to -y flag).
    """
    return [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-ar",
        str(sample_rate),
        output_path,
    ]


def _sox_remove_silence_cmd(
        input_path: str,
        output_path: str,
        silence_duration: str = DEFAULT_SILENCE_DURATION,
        silence_threshold: str = DEFAULT_SILENCE_THRESHOLD
) -> List[str]:
    """
    Build a SoX command optimized for Whisper transcription preprocessing.

    Args:
        silence_duration: Minimum silence duration to remove (e.g., "0.5" for 0.5 seconds)
        silence_threshold: Amplitude threshold for silence detection (e.g., "0.05" for 5%)
    """
    return [
        "sox",
        input_path,
        output_path,
        "silence",
        "-l",
        "1",
        silence_duration,  # minimum silence from start
        silence_threshold,  # threshold for start
        "-1",
        silence_duration,  # minimum silence from end
        silence_threshold,  # threshold for end
    ]


def convert_audio(input_path: str, output_format: str, sample_rate: int) -> str:
    """
    Convert audio format and sample rate using FFmpeg.
    Skips conversion if input already matches the target format and sample rate.
    """
    logger.info(f"Converting audio: {input_path} -> {output_format} @ {sample_rate}Hz")
    print_file_info(input_path)

    if not is_conversion_required(input_path, output_format, sample_rate):
        logger.info("Skipping conversion - no changes needed")
        return input_path

    logger.info("Starting FFmpeg conversion")
    output_path = create_temp_path(extension=output_format)
    ensure_parent_dir(output_path)

    _run_command(_ffmpeg_convert_cmd(input_path, sample_rate, output_path))
    logger.info(f"Conversion completed: {output_path}")
    print_file_info(output_path)

    return output_path


def remove_silence(
    input_path: str,
    convert_back: bool = True,
    silence_duration: str = DEFAULT_SILENCE_DURATION,
    silence_threshold: str = DEFAULT_SILENCE_THRESHOLD
) -> str:
    """
    Remove silence using SoX with configurable settings optimized for Whisper transcription.

    Args:
        input_path: Path to input audio file
        convert_back: If True, convert back to original format after processing
        silence_duration: Minimum silence duration to remove (default: 0.5 seconds)
        silence_threshold: Amplitude threshold for silence detection (default: 5%)
    """
    logger.info(f"Removing silence: {input_path} (duration={silence_duration}, threshold={silence_threshold})")
    print_file_info(input_path)

    input_ext = get_file_extension(input_path) or DEFAULT_FORMAT

    logger.debug("Converting to WAV for SoX processing")
    wav_path = convert_audio(input_path, WAVE_FORMAT, PRESERVE_SAMPLE_RATE)

    processed_wav_path = create_temp_path(extension=WAVE_FORMAT)
    ensure_parent_dir(processed_wav_path)

    logger.info("Running SoX silence removal")
    _run_command(_sox_remove_silence_cmd(wav_path, processed_wav_path, silence_duration, silence_threshold))

    if not convert_back:
        logger.info(f"Silence removal completed: {processed_wav_path}")
        print_file_info(processed_wav_path)
        return processed_wav_path
    else:
        logger.debug(f"Converting back to original format: {input_ext}")
        final_path = convert_audio(processed_wav_path, input_ext, PRESERVE_SAMPLE_RATE)
        logger.info(f"Silence removal completed: {final_path}")
        print_file_info(final_path)
        return final_path


def process_full(
        input_path: str,
        sample_rate: int,
        output_format: str,
        silence_duration: str = DEFAULT_SILENCE_DURATION,
        silence_threshold: str = DEFAULT_SILENCE_THRESHOLD
) -> str:
    """
    Combined processing: convert sample rate, then remove silence optimized for Whisper.

    Args:
        input_path: Path to input audio file
        sample_rate: Target sample rate for conversion
        output_format: Final output format
        silence_duration: Minimum silence duration to remove (default: 0.5 seconds)
        silence_threshold: Amplitude threshold for silence detection (default: 5%)
    """
    logger.info(f"Full processing: {input_path} -> {output_format} @ {sample_rate}Hz")
    print_file_info(input_path)

    converted_path = convert_audio(input_path, output_format, sample_rate)
    trimmed_path = remove_silence(
        converted_path,
        convert_back=False,
        silence_duration=silence_duration,
        silence_threshold=silence_threshold
    )

    logger.info(f"Full processing completed: {trimmed_path}")
    print_file_info(trimmed_path)
    return trimmed_path

