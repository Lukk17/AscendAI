import logging
import os
import subprocess
import time
import zipfile
import xml.etree.ElementTree as ET

from src.config.config import settings

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SAMPLE_FMT = "s16"


def _find_elements(element: ET.Element, tag_name: str):
    for child in element.iter():
        if child.tag.endswith(tag_name) or child.tag.endswith(f"}}str{tag_name}"):
            yield child
        if "}" in child.tag and child.tag.split("}")[1] == tag_name:
            yield child
        if child.tag == tag_name:
            yield child


def _run_ffmpeg(args: list[str]) -> None:
    cmd = [settings.FFMPEG_PATH] + args
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed: {e.stderr.decode(errors='replace')}")
        raise IOError(f"ffmpeg command failed with exit code {e.returncode}") from e


def _normalize_args() -> list[str]:
    return ["-ar", str(TARGET_SAMPLE_RATE), "-ac", str(TARGET_CHANNELS), "-sample_fmt", TARGET_SAMPLE_FMT]


def _convert_and_normalize(input_path: str, output_path: str, offset_ms: int = 0) -> None:
    args = ["-y", "-i", input_path]
    if offset_ms > 0:
        args += ["-af", f"adelay={offset_ms}|{offset_ms}"]
    args += _normalize_args() + [output_path]
    _run_ffmpeg(args)


def _generate_silence(output_path: str, duration_seconds: float) -> None:
    args = [
        "-y", "-f", "lavfi",
        "-i", f"anullsrc=r={TARGET_SAMPLE_RATE}:cl=mono",
        "-t", f"{duration_seconds:.6f}",
    ] + _normalize_args() + [output_path]
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


def _assemble_clip_blocks(au_files: list[str], au_file_map: dict[str, str],
                          clip_index: int, extraction_dir: str) -> str | None:
    valid_paths = []
    for au_filename in au_files:
        found_path = au_file_map.get(au_filename)
        if found_path:
            valid_paths.append(found_path)
        else:
            logger.warning(f"Could not find AU file: {au_filename}")

    if not valid_paths:
        return None

    if len(valid_paths) == 1:
        clip_wav = os.path.join(extraction_dir, f"clip_{clip_index}_{os.urandom(4).hex()}.wav")
        _convert_and_normalize(valid_paths[0], clip_wav)
        return clip_wav

    concat_list = os.path.join(extraction_dir, f"clip_{clip_index}_list.txt")
    clip_wav = os.path.join(extraction_dir, f"clip_{clip_index}_{os.urandom(4).hex()}.wav")
    _write_concat_list(valid_paths, concat_list)
    _concat_via_list(concat_list, clip_wav, normalize=True)
    return clip_wav


def _build_track_from_clips(clips: list[dict], au_file_map: dict[str, str],
                            track_idx: int, extraction_dir: str) -> str | None:
    clips.sort(key=lambda c: c["offset"])

    assembled_parts: list[str] = []
    current_time_sec = 0.0

    for clip_idx, clip in enumerate(clips):
        offset_sec = clip["offset"]

        gap_sec = offset_sec - current_time_sec
        if gap_sec > 0.001:
            gap_path = os.path.join(extraction_dir, f"gap_{track_idx}_{clip_idx}_{os.urandom(4).hex()}.wav")
            _generate_silence(gap_path, gap_sec)
            assembled_parts.append(gap_path)

        clip_wav = _assemble_clip_blocks(clip["au_files"], au_file_map, clip_idx, extraction_dir)
        if not clip_wav:
            continue

        assembled_parts.append(clip_wav)
        clip_duration = _get_audio_duration(clip_wav)
        current_time_sec = offset_sec + clip_duration

    if not assembled_parts:
        return None

    track_wav = os.path.join(extraction_dir, f"track_{track_idx}_{os.urandom(4).hex()}.wav")

    if len(assembled_parts) == 1:
        os.rename(assembled_parts[0], track_wav)
        return track_wav

    final_list = os.path.join(extraction_dir, f"track_{track_idx}_final_list.txt")
    _write_concat_list(assembled_parts, final_list)
    _concat_via_list(final_list, track_wav, normalize=False)
    return track_wav


def _get_audio_duration(file_path: str) -> float:
    cmd = [
        settings.FFMPEG_PATH.replace("ffmpeg", "ffprobe"),
        "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def extract_tracks_from_aup(zip_path: str, extraction_dir: str) -> dict[str, str]:
    logger.info(f"Extracting ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extraction_dir)

    aup_files = []
    for root_dir, dirs, files in os.walk(extraction_dir):
        for f in files:
            if f.endswith(".aup"):
                aup_files.append(os.path.join(root_dir, f))

    if not aup_files:
        raise ValueError("No .aup file found in the ZIP folder.")
    if len(aup_files) > 1:
        raise ValueError("Multiple .aup files found in the ZIP! Expected exactly one project.")

    aup_path = aup_files[0]
    aup_dir = os.path.dirname(aup_path)

    au_file_map: dict[str, str] = {}
    valid_exts = {".au", ".flac", ".wav", ".ogg", ".mp3", ".m4a"}
    for root_dir, dirs, files in os.walk(aup_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_exts:
                au_file_map[f] = os.path.join(root_dir, f)

    tree = ET.parse(aup_path)
    xml_root = tree.getroot()
    rate = float(xml_root.attrib.get('rate', 44100.0))

    tracks: dict[str, str] = {}

    imports = list(_find_elements(xml_root, "import"))
    if imports:
        return _process_craig_imports(imports, au_file_map, extraction_dir, rate, tracks)

    wavetracks = list(_find_elements(xml_root, "wavetrack"))
    return _process_standard_wavetracks(wavetracks, au_file_map, extraction_dir, tracks)


def _process_craig_imports(imports: list[ET.Element], au_file_map: dict[str, str],
                           extraction_dir: str, rate: float,
                           tracks: dict[str, str]) -> dict[str, str]:
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

        track_wav_path = os.path.join(extraction_dir, f"track_{track_idx}_{os.urandom(4).hex()}.wav")
        offset_ms = int(offset_sec * 1000)

        track_start = time.monotonic()
        _convert_and_normalize(found_path, track_wav_path, offset_ms)
        track_elapsed = time.monotonic() - track_start
        logger.info(f"Track '{track_name}' extracted in {track_elapsed:.2f}s")

        tracks[track_name] = track_wav_path

    return tracks


def _process_standard_wavetracks(wavetracks: list[ET.Element], au_file_map: dict[str, str],
                                 extraction_dir: str,
                                 tracks: dict[str, str]) -> dict[str, str]:
    logger.info(f"Found {len(wavetracks)} Standard Audacity tracks in the project.")

    for track_idx, track in enumerate(wavetracks):
        track_name = track.attrib.get("name", f"Track_{track_idx + 1}")
        logger.info(f"Processing track: {track_name}")
        track_start = time.monotonic()

        clips = _parse_clips_from_track(track)
        track_wav = _build_track_from_clips(clips, au_file_map, track_idx, extraction_dir)

        if track_wav:
            track_elapsed = time.monotonic() - track_start
            logger.info(f"Track '{track_name}' extracted in {track_elapsed:.2f}s")
            tracks[track_name] = track_wav
        else:
            logger.info(f"Track '{track_name}' is empty. Skipping.")

    return tracks


def _parse_clips_from_track(track: ET.Element) -> list[dict]:
    clips = []
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
