import logging
import os
import secrets
import subprocess
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as DET  # XXE / billion-laughs hardening for untrusted XML

from src.api.exception_handlers import FileSizeExceededError
from src.config.config import settings
from src.observability.metrics import AUDACITY_TRACKS_EXTRACTED_TOTAL, FFMPEG_INVOCATIONS_TOTAL

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SAMPLE_FMT = "s16"


def _find_elements(element: Element, tag_name: str) -> Iterator[Element]:
    for child in element.iter():
        tag = child.tag
        if tag == tag_name or ("}" in tag and tag.split("}", 1)[1] == tag_name):
            yield child


def _safe_token() -> str:
    """Cryptographically random short token for temp filename collision
    avoidance. Replaces the old os.urandom(4).hex() with the secrets' module."""

    return secrets.token_hex(4)


def _run_subprocess(binary: str, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """ffmpeg / ffprobe wrapper. Adds timeout=, records the outcome in
    FFMPEG_INVOCATIONS_TOTAL, and never passes a path-arg that could be
    parsed as a flag (caller guarantees args are already sanitised)."""

    cmd = [binary, *args]
    try:
        result = subprocess.run(  # noqa: S603 — binary is a configured path; args sanitised by caller
            cmd,
            check=True,
            capture_output=True,
            timeout=settings.FFMPEG_TIMEOUT_SECONDS,
        )
        FFMPEG_INVOCATIONS_TOTAL.labels(binary=os.path.basename(binary), outcome="success").inc()
        return result
    except subprocess.TimeoutExpired as exc:
        FFMPEG_INVOCATIONS_TOTAL.labels(binary=os.path.basename(binary), outcome="timeout").inc()
        raise OSError(
            f"{os.path.basename(binary)} timed out after {settings.FFMPEG_TIMEOUT_SECONDS}s"
        ) from exc
    except subprocess.CalledProcessError as exc:
        FFMPEG_INVOCATIONS_TOTAL.labels(binary=os.path.basename(binary), outcome="error").inc()
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        logger.exception(f"{binary} failed: {stderr}")
        raise OSError(f"{os.path.basename(binary)} command failed with exit code {exc.returncode}") from exc


def _run_ffmpeg(args: list[str]) -> None:
    _run_subprocess(settings.FFMPEG_PATH, args)


def _normalize_args() -> list[str]:
    return ["-ar", str(TARGET_SAMPLE_RATE), "-ac", str(TARGET_CHANNELS), "-sample_fmt", TARGET_SAMPLE_FMT]


def _convert_and_normalize(input_path: str, output_path: str, offset_ms: int = 0) -> None:
    args = ["-y", "-i", input_path]
    if offset_ms > 0:
        args += ["-af", f"adelay={offset_ms}|{offset_ms}"]
    args += [*_normalize_args(), output_path]
    _run_ffmpeg(args)


def _generate_silence(output_path: str, duration_seconds: float) -> None:
    args = [
        "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r={TARGET_SAMPLE_RATE}:cl=mono",
        "-t", f"{duration_seconds:.6f}",
        *_normalize_args(),
        output_path,
    ]
    _run_ffmpeg(args)


def _write_concat_list(file_paths: list[str], list_file_path: str) -> None:
    with open(list_file_path, "w", encoding="utf-8") as f:
        for path in file_paths:
            safe_path = path.replace("\\", "/")
            f.write(f"file '{safe_path}'\n")


def _concat_via_list(concat_list_path: str, output_path: str, normalize: bool = True) -> None:
    args = ["-y", "-f", "concat", "-safe", "0", "-i", concat_list_path]
    if normalize:
        args += _normalize_args()
    else:
        args += ["-c", "copy"]
    args.append(output_path)
    _run_ffmpeg(args)


def _assemble_clip_blocks(
    au_files: list[str], au_file_map: dict[str, str], clip_index: int, extraction_dir: str
) -> str | None:
    valid_paths = [au_file_map[name] for name in au_files if name in au_file_map]
    if len(valid_paths) != len(au_files):
        missing = [name for name in au_files if name not in au_file_map]
        for name in missing:
            logger.warning(f"Could not find AU file: {name}")

    if not valid_paths:
        return None

    clip_wav = os.path.join(extraction_dir, f"clip_{clip_index}_{_safe_token()}.wav")
    if len(valid_paths) == 1:
        _convert_and_normalize(valid_paths[0], clip_wav)
        return clip_wav

    concat_list = os.path.join(extraction_dir, f"clip_{clip_index}_list.txt")
    _write_concat_list(valid_paths, concat_list)
    _concat_via_list(concat_list, clip_wav, normalize=True)
    return clip_wav


def _build_track_from_clips(
    clips: list[dict[str, Any]], au_file_map: dict[str, str], track_idx: int, extraction_dir: str
) -> str | None:
    clips.sort(key=lambda c: float(c["offset"]))

    assembled_parts: list[str] = []
    current_time_sec = 0.0

    for clip_idx, clip in enumerate(clips):
        offset_sec = float(clip["offset"])

        gap_sec = offset_sec - current_time_sec
        if gap_sec > 0.001:
            gap_path = os.path.join(
                extraction_dir, f"gap_{track_idx}_{clip_idx}_{_safe_token()}.wav"
            )
            _generate_silence(gap_path, gap_sec)
            assembled_parts.append(gap_path)

        au_files = clip["au_files"]
        clip_wav = _assemble_clip_blocks(au_files, au_file_map, clip_idx, extraction_dir)
        if not clip_wav:
            continue

        assembled_parts.append(clip_wav)
        current_time_sec = offset_sec + _get_audio_duration(clip_wav)

    if not assembled_parts:
        return None

    track_wav = os.path.join(extraction_dir, f"track_{track_idx}_{_safe_token()}.wav")
    if len(assembled_parts) == 1:
        os.rename(assembled_parts[0], track_wav)
        return track_wav

    final_list = os.path.join(extraction_dir, f"track_{track_idx}_final_list.txt")
    _write_concat_list(assembled_parts, final_list)
    _concat_via_list(final_list, track_wav, normalize=False)
    return track_wav


def _get_audio_duration(file_path: str) -> float:
    args = [
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    result = _run_subprocess(settings.FFPROBE_PATH, args)
    return float(result.stdout.decode().strip())


_VALID_AUDIO_EXTS = frozenset({".au", ".flac", ".wav", ".ogg", ".mp3", ".m4a"})


def _check_zip_size_cap(total_uncompressed: int) -> None:
    cap = settings.MAX_ZIP_UNCOMPRESSED_BYTES
    if total_uncompressed > cap:
        raise FileSizeExceededError(f"Audacity zip uncompressed size exceeds {cap} bytes")


def _handle_zip_directory_entry(name: str, root: Path) -> None:
    target_dir = (root / name).resolve()
    if not target_dir.is_relative_to(root):
        raise ValueError(f"Zip directory entry escapes extraction root: {name}")
    target_dir.mkdir(parents=True, exist_ok=True)


def _resolve_zip_member_target(name: str, root: Path) -> Path:
    """Compute the on-disk target for a zip member, after stripping absolute
    prefixes and renaming any flag-shaped basenames (`-foo.wav` →
    `_dash_<token>.wav`) so ffmpeg can never mis-parse the path as a flag."""

    sanitised = name.lstrip("/\\")
    stem = Path(sanitised).name
    if stem.startswith("-"):
        renamed = f"_dash_{_safe_token()}{Path(sanitised).suffix}"
        sanitised = str(Path(sanitised).parent / renamed)
    target = (root / sanitised).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"Zip member escapes extraction root: {name}")
    return target


def _stream_member_to_disk(
    zip_ref: zipfile.ZipFile, member: zipfile.ZipInfo, target: Path
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zip_ref.open(member) as src, target.open("wb") as dst:
        while True:
            chunk = src.read(settings.UPLOAD_BUFFER_BYTES)
            if not chunk:
                break
            dst.write(chunk)


def _safe_zip_extract(zip_path: str, extraction_dir: str) -> None:
    """Zip-slip + size-cap + symlink-rejection guarded extractor."""

    root = Path(extraction_dir).resolve()
    total_uncompressed = 0

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            total_uncompressed += member.file_size
            _check_zip_size_cap(total_uncompressed)

            name = member.filename
            if not name or name.endswith("/"):
                _handle_zip_directory_entry(name, root)
                continue

            target = _resolve_zip_member_target(name, root)
            _stream_member_to_disk(zip_ref, member, target)


def _find_single_aup_path(extraction_dir: str) -> str:
    aup_files: list[str] = []
    for root_dir, _, files in os.walk(extraction_dir):
        for f in files:
            if f.endswith(".aup"):
                aup_files.append(os.path.join(root_dir, f))

    if not aup_files:
        raise ValueError("No .aup file found in the ZIP folder.")
    if len(aup_files) > 1:
        raise ValueError("Multiple .aup files found in the ZIP! Expected exactly one project.")
    return aup_files[0]


def _build_au_file_map(aup_dir: str) -> dict[str, str]:
    au_file_map: dict[str, str] = {}
    for root_dir, _, files in os.walk(aup_dir):
        for f in files:
            if os.path.splitext(f)[1].lower() in _VALID_AUDIO_EXTS:
                au_file_map[f] = os.path.join(root_dir, f)
    return au_file_map


def _parse_aup_root(aup_path: str) -> Element:
    tree = DET.parse(aup_path)
    xml_root: Element | None = tree.getroot()
    if xml_root is None:
        raise ValueError("AUP file has no root element")
    return xml_root


def extract_tracks_from_aup(zip_path: str, extraction_dir: str) -> dict[str, str]:
    logger.info(f"Extracting ZIP: {zip_path}")
    _safe_zip_extract(zip_path, extraction_dir)

    aup_path = _find_single_aup_path(extraction_dir)
    aup_dir = os.path.dirname(aup_path)
    au_file_map = _build_au_file_map(aup_dir)

    xml_root = _parse_aup_root(aup_path)
    rate = float(xml_root.attrib.get("rate", 44100.0))

    tracks: dict[str, str] = {}
    imports = list(_find_elements(xml_root, "import"))
    if imports:
        tracks = _process_craig_imports(imports, au_file_map, extraction_dir, rate, tracks)
    else:
        wavetracks = list(_find_elements(xml_root, "wavetrack"))
        tracks = _process_standard_wavetracks(wavetracks, au_file_map, extraction_dir, tracks)

    if tracks:
        AUDACITY_TRACKS_EXTRACTED_TOTAL.inc(len(tracks))
    return tracks


def _process_craig_imports(
    imports: list[Element],
    au_file_map: dict[str, str],
    extraction_dir: str,
    rate: float,
    tracks: dict[str, str],
) -> dict[str, str]:
    del rate  # The Craig path overrides offset directly; rate is informational only.
    logger.info(f"Found {len(imports)} Craig/import tracks in the project.")
    for track_idx, imp in enumerate(imports):
        filename = imp.attrib.get("filename")
        if not filename:
            continue

        offset_sec = float(imp.attrib.get("offset", 0.0))
        track_name = os.path.splitext(filename)[0]

        found_path = au_file_map.get(filename) or au_file_map.get(os.path.basename(filename))
        if not found_path:
            logger.warning(f"Could not find imported file: {filename}")
            continue

        track_wav_path = os.path.join(
            extraction_dir, f"track_{track_idx}_{_safe_token()}.wav"
        )
        offset_ms = int(offset_sec * 1000)

        track_start = time.monotonic()
        _convert_and_normalize(found_path, track_wav_path, offset_ms)
        logger.info(
            f"Track '{track_name}' extracted in {time.monotonic() - track_start:.2f}s"
        )

        tracks[track_name] = track_wav_path

    return tracks


def _process_standard_wavetracks(
    wavetracks: list[Element],
    au_file_map: dict[str, str],
    extraction_dir: str,
    tracks: dict[str, str],
) -> dict[str, str]:
    logger.info(f"Found {len(wavetracks)} Standard Audacity tracks in the project.")

    for track_idx, track in enumerate(wavetracks):
        track_name = track.attrib.get("name", f"Track_{track_idx + 1}")
        logger.info(f"Processing track: {track_name}")
        track_start = time.monotonic()

        clips = _parse_clips_from_track(track)
        track_wav = _build_track_from_clips(clips, au_file_map, track_idx, extraction_dir)

        if track_wav:
            logger.info(
                f"Track '{track_name}' extracted in {time.monotonic() - track_start:.2f}s"
            )
            tracks[track_name] = track_wav
        else:
            logger.info(f"Track '{track_name}' is empty. Skipping.")

    return tracks


def _parse_clips_from_track(track: Element) -> list[dict[str, object]]:
    clips: list[dict[str, object]] = []
    for clip in _find_elements(track, "waveclip"):
        offset_sec = float(clip.attrib.get("offset", 0.0))
        au_files_in_clip: list[str] = []

        blocks = list(_find_elements(clip, "waveblock"))
        blocks.sort(key=lambda b: int(b.attrib.get("start", 0)))

        for block in blocks:
            for simplefile in _find_elements(block, "simpleblockfile"):
                filename = simplefile.attrib.get("filename")
                if filename:
                    au_files_in_clip.append(filename)

            for aliasfile in _find_elements(block, "pcmaliasblockfile"):
                filename = aliasfile.attrib.get("aliasfile")
                if filename:
                    au_files_in_clip.append(os.path.basename(filename))

        clips.append({"offset": offset_sec, "au_files": au_files_in_clip})
    return clips
