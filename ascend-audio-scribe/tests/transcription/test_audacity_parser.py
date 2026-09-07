import subprocess
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.api.exception_handlers import FileSizeExceededError
from src.transcription import audacity_parser as ap


def _make_zip(zip_path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def test_safe_token_length() -> None:
    assert len(ap._safe_token()) == 8


def test_normalize_args_shape() -> None:
    assert ap._normalize_args()[:2] == ["-ar", "16000"]


def test_run_subprocess_records_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = MagicMock(returncode=0)
    monkeypatch.setattr(ap.subprocess, "run", MagicMock(return_value=fake))
    result = ap._run_subprocess("ffmpeg", ["-y"])
    assert result is fake


def test_run_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ap.subprocess, "run", MagicMock(side_effect=subprocess.TimeoutExpired("ffmpeg", 1))
    )
    with pytest.raises(OSError, match="timed out"):
        ap._run_subprocess("ffmpeg", ["-y"])


def test_run_subprocess_called_process_error(monkeypatch: pytest.MonkeyPatch) -> None:
    err = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"bad")
    monkeypatch.setattr(ap.subprocess, "run", MagicMock(side_effect=err))
    with pytest.raises(OSError, match="exit code 1"):
        ap._run_subprocess("ffmpeg", ["-y"])


def test_run_subprocess_called_process_error_no_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    err = subprocess.CalledProcessError(2, "ffmpeg", stderr=None)
    monkeypatch.setattr(ap.subprocess, "run", MagicMock(side_effect=err))
    with pytest.raises(OSError, match="exit code 2"):
        ap._run_subprocess("ffmpeg", ["-y"])


def test_run_ffmpeg_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    sub = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(ap, "_run_subprocess", sub)
    ap._run_ffmpeg(["-i", "x"])
    sub.assert_called_once_with(ap.settings.FFMPEG_PATH, ["-i", "x"])


def test_convert_and_normalize_with_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run = MagicMock()
    monkeypatch.setattr(ap, "_run_ffmpeg", fake_run)
    ap._convert_and_normalize("in.wav", "out.wav", offset_ms=500)
    args = fake_run.call_args.args[0]
    assert "-af" in args
    assert any("adelay=500" in a for a in args)


def test_generate_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ap, "_run_ffmpeg", MagicMock())
    ap._generate_silence("silence.wav", 0.5)


def test_write_and_concat_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    list_path = tmp_path / "list.txt"
    ap._write_concat_list([str(tmp_path / "a.wav"), str(tmp_path / "b.wav")], str(list_path))
    body = list_path.read_text(encoding="utf-8")
    assert "a.wav" in body
    assert "b.wav" in body


def test_concat_via_list_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ap, "_run_ffmpeg", MagicMock())
    ap._concat_via_list("list.txt", "out.wav", normalize=False)
    ap._concat_via_list("list.txt", "out.wav", normalize=True)


def test_assemble_clip_blocks_single(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ap, "_convert_and_normalize", MagicMock())
    out = ap._assemble_clip_blocks(["one.au"], {"one.au": "/tmp/one.au"}, 0, str(tmp_path))
    assert out is not None


def test_assemble_clip_blocks_concat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ap, "_write_concat_list", MagicMock())
    monkeypatch.setattr(ap, "_concat_via_list", MagicMock())
    out = ap._assemble_clip_blocks(
        ["a.au", "b.au"],
        {"a.au": "/x/a.au", "b.au": "/x/b.au"},
        1,
        str(tmp_path),
    )
    assert out is not None


def test_assemble_clip_blocks_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert ap._assemble_clip_blocks(["missing.au"], {}, 0, str(tmp_path)) is None


def test_build_track_from_clips_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert ap._build_track_from_clips([], {}, 0, str(tmp_path)) is None


def test_build_track_from_clips_single_with_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ap, "_generate_silence", MagicMock())
    monkeypatch.setattr(
        ap, "_assemble_clip_blocks", MagicMock(return_value=str(tmp_path / "clip.wav"))
    )
    monkeypatch.setattr(ap, "_get_audio_duration", MagicMock(return_value=1.0))
    monkeypatch.setattr(ap, "_write_concat_list", MagicMock())
    monkeypatch.setattr(ap, "_concat_via_list", MagicMock())
    (tmp_path / "clip.wav").write_bytes(b"x")
    clips = [{"offset": 0.5, "au_files": ["x.au"]}]
    out = ap._build_track_from_clips(clips, {"x.au": str(tmp_path / "x")}, 0, str(tmp_path))
    assert out is not None


def test_build_track_from_clips_multi_concat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = [str(tmp_path / f"c{i}.wav") for i in range(3)]
    for p in paths:
        Path(p).write_bytes(b"x")
    monkeypatch.setattr(ap, "_generate_silence", MagicMock())
    monkeypatch.setattr(ap, "_assemble_clip_blocks", MagicMock(side_effect=paths))
    monkeypatch.setattr(ap, "_get_audio_duration", MagicMock(return_value=1.0))
    monkeypatch.setattr(ap, "_write_concat_list", MagicMock())
    monkeypatch.setattr(ap, "_concat_via_list", MagicMock())
    clips = [
        {"offset": 0.0, "au_files": ["a.au"]},
        {"offset": 1.0, "au_files": ["b.au"]},
        {"offset": 2.0, "au_files": ["c.au"]},
    ]
    out = ap._build_track_from_clips(clips, {f"{name}.au": "/x" for name in "abc"}, 0, str(tmp_path))
    assert out is not None


def test_build_track_from_clips_skips_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ap, "_assemble_clip_blocks", MagicMock(return_value=None))
    clips = [{"offset": 0.0, "au_files": ["x.au"]}]
    out = ap._build_track_from_clips(clips, {}, 0, str(tmp_path))
    assert out is None


def test_get_audio_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_result = MagicMock()
    fake_result.stdout = b"3.14\n"
    monkeypatch.setattr(ap, "_run_subprocess", MagicMock(return_value=fake_result))
    assert ap._get_audio_duration("x.wav") == pytest.approx(3.14)


def test_safe_zip_extract_rejects_traversal(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    # Create a zip with a traversal entry. We need to bypass ZipFile's sanitization
    # by constructing the zip raw bytes — alternative: use a relative path that resolves outside.
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo(filename="../escape.txt")
        zf.writestr(info, b"bad")
    extract = tmp_path / "out"
    extract.mkdir()
    with pytest.raises(ValueError, match="escapes"):
        ap._safe_zip_extract(str(zip_path), str(extract))


def test_safe_zip_extract_rejects_directory_traversal(tmp_path: Path) -> None:
    zip_path = tmp_path / "baddir.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        info = zipfile.ZipInfo(filename="../baddir/")
        zf.writestr(info, b"")
    extract = tmp_path / "out2"
    extract.mkdir()
    with pytest.raises(ValueError, match="directory entry escapes"):
        ap._safe_zip_extract(str(zip_path), str(extract))


def test_safe_zip_extract_size_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zip_path = tmp_path / "big.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("big.bin", b"x" * 10_000)
    extract = tmp_path / "ok"
    extract.mkdir()
    monkeypatch.setattr(ap.settings, "MAX_ZIP_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(FileSizeExceededError):
        ap._safe_zip_extract(str(zip_path), str(extract))


def test_safe_zip_extract_renames_dash_prefix(tmp_path: Path) -> None:
    zip_path = tmp_path / "dash.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("-flagshape.wav", b"data")
    extract = tmp_path / "ok2"
    extract.mkdir()
    ap._safe_zip_extract(str(zip_path), str(extract))
    files = list(extract.iterdir())
    assert files
    assert not files[0].name.startswith("-")


def test_safe_zip_extract_handles_directory_entry(tmp_path: Path) -> None:
    zip_path = tmp_path / "dir.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("subdir/", b"")
        zf.writestr("subdir/file.txt", b"x")
    extract = tmp_path / "ok3"
    extract.mkdir()
    ap._safe_zip_extract(str(zip_path), str(extract))
    assert (extract / "subdir" / "file.txt").exists()


def _build_minimal_aup_zip(zip_path: Path, *, kind: str) -> None:
    """Create a minimal valid Audacity project zip for parser exercising."""
    if kind == "craig":
        aup_xml = (
            '<?xml version="1.0"?>'
            '<project xmlns="http://audacity.sourceforge.net/xml/" rate="44100.0">'
            '  <import filename="speaker_a.wav" offset="0.0"/>'
            '</project>'
        )
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("project.aup", aup_xml)
            zf.writestr("speaker_a.wav", b"\x00" * 16)
    elif kind == "wavetrack":
        aup_xml = (
            '<?xml version="1.0"?>'
            '<project xmlns="http://audacity.sourceforge.net/xml/" rate="44100.0">'
            '  <wavetrack name="Track1">'
            '    <waveclip offset="0.0">'
            '      <waveblock start="0">'
            '        <simpleblockfile filename="b0.au"/>'
            '      </waveblock>'
            '    </waveclip>'
            '  </wavetrack>'
            '</project>'
        )
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("project.aup", aup_xml)
            zf.writestr("b0.au", b"\x00" * 16)


def test_extract_tracks_no_aup_in_zip(tmp_path: Path) -> None:
    zip_path = tmp_path / "no_aup.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("foo.txt", b"x")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match=r"No .aup"):
        ap.extract_tracks_from_aup(str(zip_path), str(out))


def test_extract_tracks_multiple_aups(tmp_path: Path) -> None:
    zip_path = tmp_path / "multi.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.aup", b"<x/>")
        zf.writestr("b.aup", b"<x/>")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="Multiple"):
        ap.extract_tracks_from_aup(str(zip_path), str(out))


def test_extract_tracks_craig_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zip_path = tmp_path / "craig.zip"
    _build_minimal_aup_zip(zip_path, kind="craig")
    out = tmp_path / "out_c"
    out.mkdir()
    monkeypatch.setattr(ap, "_convert_and_normalize", MagicMock())
    tracks = ap.extract_tracks_from_aup(str(zip_path), str(out))
    assert "speaker_a" in tracks


def test_extract_tracks_wavetrack_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zip_path = tmp_path / "wt.zip"
    _build_minimal_aup_zip(zip_path, kind="wavetrack")
    out = tmp_path / "out_w"
    out.mkdir()
    monkeypatch.setattr(ap, "_convert_and_normalize", MagicMock())
    monkeypatch.setattr(ap, "_assemble_clip_blocks", MagicMock(return_value=str(out / "clip.wav")))
    monkeypatch.setattr(ap, "_get_audio_duration", MagicMock(return_value=1.0))
    (out / "clip.wav").write_bytes(b"x")
    tracks = ap.extract_tracks_from_aup(str(zip_path), str(out))
    assert "Track1" in tracks


def test_process_craig_imports_skips_no_filename(tmp_path: Path) -> None:
    from xml.etree.ElementTree import Element

    el = Element("import")
    tracks = ap._process_craig_imports([el], {}, str(tmp_path), 44100.0, {})
    assert tracks == {}


def test_process_craig_imports_skips_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from xml.etree.ElementTree import Element

    el = Element("import")
    el.set("filename", "absent.wav")
    el.set("offset", "0.0")
    tracks = ap._process_craig_imports([el], {}, str(tmp_path), 44100.0, {})
    assert tracks == {}


def test_process_standard_wavetracks_handles_empty(tmp_path: Path) -> None:
    tracks = ap._process_standard_wavetracks([], {}, str(tmp_path), {})
    assert tracks == {}


def test_process_standard_wavetracks_logs_empty_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from xml.etree.ElementTree import Element

    track = Element("wavetrack")
    track.set("name", "Empty1")
    monkeypatch.setattr(ap, "_parse_clips_from_track", lambda _t: [])
    monkeypatch.setattr(ap, "_build_track_from_clips", lambda *_a, **_kw: None)
    out = ap._process_standard_wavetracks([track], {}, str(tmp_path), {})
    assert out == {}


def test_parse_clips_skips_empty_simpleblockfile_filename() -> None:
    """A `<simpleblockfile>` element with a missing/empty `filename` attr
    must not be appended to au_files (else the assemble step explodes
    looking up the empty key)."""

    from xml.etree.ElementTree import Element

    track = Element("wavetrack")
    clip = Element("waveclip")
    clip.set("offset", "0.0")
    block = Element("waveblock")
    block.set("start", "0")
    simple = Element("simpleblockfile")
    # No `filename` attribute set — should be silently skipped.
    block.append(simple)
    clip.append(block)
    track.append(clip)
    clips = ap._parse_clips_from_track(track)
    assert clips[0]["au_files"] == []


def test_parse_clips_skips_empty_pcmaliasblockfile_aliasfile() -> None:
    from xml.etree.ElementTree import Element

    track = Element("wavetrack")
    clip = Element("waveclip")
    clip.set("offset", "0.0")
    block = Element("waveblock")
    block.set("start", "0")
    alias = Element("pcmaliasblockfile")
    # No `aliasfile` attribute — silently skipped.
    block.append(alias)
    clip.append(block)
    track.append(clip)
    clips = ap._parse_clips_from_track(track)
    assert clips[0]["au_files"] == []


def test_extract_tracks_returns_empty_when_aup_has_no_tracks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the AUP file has neither `<import>` nor `<wavetrack>` elements
    the returned dict is empty — and the metric inc is skipped (covers the
    `if tracks:` False branch in extract_tracks_from_aup)."""

    import zipfile as _zip

    zip_path = tmp_path / "barren.zip"
    aup_xml = (
        '<?xml version="1.0"?>'
        '<project xmlns="http://audacity.sourceforge.net/xml/" rate="44100.0">'
        '</project>'
    )
    with _zip.ZipFile(zip_path, "w") as zf:
        zf.writestr("project.aup", aup_xml)
    out = tmp_path / "out_barren"
    out.mkdir()
    tracks = ap.extract_tracks_from_aup(str(zip_path), str(out))
    assert tracks == {}


def test_convert_and_normalize_without_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    """offset_ms=0 → no -af adelay arg appears in the ffmpeg command."""

    fake_run = MagicMock()
    monkeypatch.setattr(ap, "_run_ffmpeg", fake_run)
    ap._convert_and_normalize("in.wav", "out.wav", offset_ms=0)
    args = fake_run.call_args.args[0]
    assert "-af" not in args


def test_parse_clips_handles_pcmaliasblockfile() -> None:
    from xml.etree.ElementTree import Element

    track = Element("wavetrack")
    clip = Element("waveclip")
    clip.set("offset", "0.0")
    block = Element("waveblock")
    block.set("start", "0")
    alias = Element("pcmaliasblockfile")
    alias.set("aliasfile", "/abs/path/to/external.wav")
    block.append(alias)
    clip.append(block)
    track.append(clip)
    clips = ap._parse_clips_from_track(track)
    assert clips
    assert clips[0]["au_files"] == ["external.wav"]


def test_extract_tracks_handles_missing_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zipfile

    zip_path = tmp_path / "p.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("p.aup", "<x/>")
    out = tmp_path / "out_null"
    out.mkdir()

    class _Tree:
        def getroot(self) -> None:
            return None

    monkeypatch.setattr(ap.DET, "parse", lambda _path: _Tree())
    with pytest.raises(ValueError, match="no root element"):
        ap.extract_tracks_from_aup(str(zip_path), str(out))
