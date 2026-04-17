import logging
import os
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from pydub import AudioSegment

logger = logging.getLogger(__name__)


def _find_elements(element: ET.Element, tag_name: str):
    """Safely yields elements ignoring XML namespaces."""
    for child in element.iter():
        if child.tag.endswith(tag_name) or child.tag.endswith(f"}}str{tag_name}"):
            yield child
        if "}" in child.tag and child.tag.split("}")[1] == tag_name:
            yield child
        if child.tag == tag_name:
            yield child


def extract_tracks_from_aup(zip_path: str, extraction_dir: str) -> dict[str, str]:
    """
    Extracts an Audacity .aup project from a zip and synthesizes tracks.
    Returns a dictionary of {track_name: extracted_wav_path}.
    """
    logger.info(f"Extracting ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extraction_dir)

    aup_files = []
    for root, dirs, files in os.walk(extraction_dir):
        for f in files:
            if f.endswith(".aup"):
                aup_files.append(os.path.join(root, f))

    if not aup_files:
        raise ValueError("No .aup file found in the ZIP folder.")
    if len(aup_files) > 1:
        raise ValueError("Multiple .aup files found in the ZIP! Expected exactly one project.")

    aup_path = aup_files[0]
    aup_dir = os.path.dirname(aup_path)

    au_file_map = {}
    valid_exts = {".au", ".flac", ".wav", ".ogg", ".mp3", ".m4a"}
    for root, dirs, files in os.walk(aup_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_exts:
                au_file_map[f] = os.path.join(root, f)

    tree = ET.parse(aup_path)
    root = tree.getroot()
    rate = float(root.attrib.get('rate', 44100.0))

    tracks = {}

    # Handle Craig Bot native <import> exports
    imports = list(_find_elements(root, "import"))
    if imports:
        logger.info(f"Found {len(imports)} Craig/import tracks in the project.")
        for track_idx, imp in enumerate(imports):
            filename = imp.attrib.get("filename")
            offset_sec = float(imp.attrib.get("offset", 0.0))
            track_name = os.path.splitext(filename)[0]
            
            if not filename:
                continue

            found_path = au_file_map.get(filename)
            if not found_path:
                # Also try matching just the basename in case the XML uses relative paths
                found_path = au_file_map.get(os.path.basename(filename))
                
            if not found_path:
                logger.warning(f"Could not find imported file: {filename}")
                continue

            try:
                clip_audio = AudioSegment.from_file(found_path)
            except Exception as e:
                logger.warning(f"Failed to load clip {filename}: {e}")
                continue

            offset_ms = int(offset_sec * 1000)
            if offset_ms > 0:
                clip_audio = AudioSegment.silent(duration=offset_ms, frame_rate=int(rate)).set_channels(1).set_sample_width(2) + clip_audio

            track_wav_path = os.path.join(extraction_dir, f"track_{track_idx}_{os.urandom(4).hex()}.wav")
            clip_audio = clip_audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            clip_audio.export(track_wav_path, format="wav")
            tracks[track_name] = track_wav_path

        return tracks

    wavetracks = list(_find_elements(root, "wavetrack"))
    logger.info(f"Found {len(wavetracks)} Standard Audacity tracks in the project.")

    for track_idx, track in enumerate(wavetracks):
        track_name = track.attrib.get("name", f"Track_{track_idx + 1}")
        logger.info(f"Processing track: {track_name}")

        track_audio = AudioSegment.silent(duration=0, frame_rate=int(rate))
        track_audio = track_audio.set_channels(1).set_sample_width(2)

        clips = []
        for clip in _find_elements(track, "waveclip"):
            offset_sec = float(clip.attrib.get("offset", 0.0))
            au_files_in_clip = []

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
                        basename = os.path.basename(filename)
                        au_files_in_clip.append(basename)

            clips.append({"offset": offset_sec, "au_files": au_files_in_clip})

        clips.sort(key=lambda c: c["offset"])
        current_time_ms = 0

        for clip in clips:
            offset_ms = int(clip["offset"] * 1000)

            if offset_ms > current_time_ms:
                track_audio += AudioSegment.silent(duration=(offset_ms - current_time_ms), frame_rate=int(rate))
                current_time_ms = offset_ms

            clip_audio = AudioSegment.silent(duration=0, frame_rate=int(rate))
            for au_filename in clip["au_files"]:
                found_path = au_file_map.get(au_filename)
                if found_path:
                    try:
                        au_segment = AudioSegment.from_file(found_path)
                        clip_audio += au_segment
                    except Exception as e:
                        logger.warning(f"Failed to load clip {au_filename}: {e}")
                else:
                    logger.warning(f"Could not find AU file: {au_filename}")

            track_audio += clip_audio
            current_time_ms += len(clip_audio)

        if len(track_audio) > 0:
            track_wav_path = os.path.join(extraction_dir, f"track_{track_idx}_{os.urandom(4).hex()}.wav")
            track_audio = track_audio.set_frame_rate(16000).set_channels(1)
            track_audio.export(track_wav_path, format="wav")
            tracks[track_name] = track_wav_path
        else:
            logger.info(f"Track '{track_name}' is empty. Skipping.")

    return tracks
