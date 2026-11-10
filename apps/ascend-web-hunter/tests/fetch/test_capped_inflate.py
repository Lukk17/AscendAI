"""Bounded reads of compressed HTTP bodies, and the capped gzip file layer."""

import gzip
import random
import zlib
from collections.abc import AsyncIterator
from typing import Any

import brotli
import pytest
import zstandard
from curl_cffi.requests.headers import Headers

from src.fetch import capped_inflate
from src.fetch.capped_inflate import (
    BodyOverLimitError,
    ContentDecodingError,
    declared_content_length,
    drain_inflated,
    gunzip_capped,
    read_inflated_body,
    read_inflated_prefix,
)

_MAX_BYTES = 8
_PAGE = b"<html><body>" + b"zazolc gesla jazn " * 5000 + b"</body></html>"
_BOMB_SIZE = 16 * 1024 * 1024
_ROOM_FOR_SHORT_PAGE = 256
_EMPTY_STORED_DEFLATE_BLOCK = b"\x00\x00\x00\xff\xff"
_ZLIB_HEADER = b"\x78\x01"
_GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
_SECOND_STEP_FACTOR = 2


def _raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)

    return compressor.compress(data) + compressor.flush()


_ENCODERS = {
    "gzip": gzip.compress,
    "x-gzip": gzip.compress,
    "deflate": zlib.compress,
    "br": brotli.compress,
    "zstd": zstandard.ZstdCompressor().compress,
}


class _Streamed:
    def __init__(
        self,
        *chunks: bytes,
        content_encoding: str | None = None,
        content_length: int | None = None,
    ) -> None:
        headers: list[tuple[str, str]] = []
        if content_encoding is not None:
            headers.append(("Content-Encoding", content_encoding))
        if content_length is not None:
            headers.append(("Content-Length", str(content_length)))
        self.headers = Headers(headers)
        self.chunks_read = 0
        self._chunks = chunks

    async def aiter_content(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk


def _single_bytes(data: bytes) -> tuple[bytes, ...]:
    return tuple(data[index : index + 1] for index in range(len(data)))


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_compressed_body_reads_back_whole(coding: str) -> None:
    # given
    response = _Streamed(_ENCODERS[coding](_PAGE), content_encoding=coding)

    # when
    body = await read_inflated_body(response, len(_PAGE))

    # then
    assert body == _PAGE


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_compressed_body_split_into_single_bytes_reads_back_whole(coding: str) -> None:
    # given
    page = b"short page"
    response = _Streamed(*_single_bytes(_ENCODERS[coding](page)), content_encoding=coding)

    # when
    body = await read_inflated_body(response, _ROOM_FOR_SHORT_PAGE)

    # then
    assert body == page


async def test_a_raw_deflate_body_without_a_zlib_header_reads_back_whole() -> None:
    # given a server that sends deflate without the zlib wrapper
    response = _Streamed(_raw_deflate(_PAGE), content_encoding="deflate")

    # when
    body = await read_inflated_body(response, len(_PAGE))

    # then
    assert body == _PAGE


async def test_a_deflate_body_cut_after_one_byte_answers_nothing() -> None:
    # given
    response = _Streamed(zlib.compress(_PAGE)[:1], content_encoding="deflate")

    # when
    body = await read_inflated_body(response, len(_PAGE))

    # then
    assert body == b""


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_body_one_byte_over_the_limit_answers_none(coding: str) -> None:
    # given
    response = _Streamed(_ENCODERS[coding](_PAGE), content_encoding=coding)

    # when
    body = await read_inflated_body(response, len(_PAGE) - 1)

    # then
    assert body is None


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_bomb_stops_near_the_limit_in_bounded_pieces(coding: str) -> None:
    # given
    limit = 1024 * 1024
    response = _Streamed(_ENCODERS[coding](bytes(_BOMB_SIZE)), content_encoding=coding)
    pieces: list[int] = []

    # when
    with pytest.raises(BodyOverLimitError):
        await drain_inflated(response, limit, lambda piece: pieces.append(len(piece)))

    # then
    assert sum(pieces) == limit
    assert max(pieces) <= _SECOND_STEP_FACTOR * capped_inflate._INFLATE_STEP_BYTES


async def test_stacked_codings_are_undone_last_applied_first() -> None:
    # given
    wire = brotli.compress(gzip.compress(_PAGE))
    response = _Streamed(wire, content_encoding="gzip, br")

    # when
    body = await read_inflated_body(response, len(_PAGE))

    # then
    assert body == _PAGE


@pytest.mark.parametrize("coding", [None, "", "identity", "none", " Identity ", "identity, none"])
async def test_a_body_with_no_real_coding_passes_through(coding: str | None) -> None:
    # given
    response = _Streamed(b"plain ", b"text", content_encoding=coding)

    # when
    body = await read_inflated_body(response, 10)

    # then
    assert body == b"plain text"


async def test_a_coding_name_is_matched_in_any_case() -> None:
    # given
    response = _Streamed(gzip.compress(_PAGE), content_encoding="GZIP")

    # when
    body = await read_inflated_body(response, len(_PAGE))

    # then
    assert body == _PAGE


async def test_an_unsupported_coding_is_refused_before_reading() -> None:
    # given
    response = _Streamed(b"x", content_encoding="compress")

    # when / then
    with pytest.raises(ContentDecodingError, match="compress"):
        await read_inflated_body(response, 10)
    assert response.chunks_read == 0


async def test_more_stacked_codings_than_the_limit_are_refused() -> None:
    # given
    response = _Streamed(b"x", content_encoding=", ".join(["gzip"] * 6))

    # when / then
    with pytest.raises(ContentDecodingError, match="too many"):
        await read_inflated_body(response, 10)


@pytest.mark.parametrize("coding", ["gzip", "br", "zstd", "deflate"])
async def test_a_corrupt_body_raises_the_decoding_error(coding: str) -> None:
    # given
    wire = b"\xff" * 64 if coding != "gzip" else b"\x1f\x8b\x00not a deflate stream"
    response = _Streamed(wire, content_encoding=coding)

    # when / then
    with pytest.raises(ContentDecodingError):
        await read_inflated_body(response, 1024)


async def test_a_gzip_body_cut_before_its_trailer_answers_what_arrived() -> None:
    # given
    response = _Streamed(gzip.compress(_PAGE)[:-10], content_encoding="gzip")

    # when
    body = await read_inflated_body(response, len(_PAGE))

    # then
    assert body is not None
    assert _PAGE.startswith(body)
    assert len(body) > len(_PAGE) // 2


@pytest.mark.parametrize("coding", ["gzip", "br"])
async def test_bytes_after_the_end_of_the_stream_are_ignored(coding: str) -> None:
    # given
    response = _Streamed(_ENCODERS[coding](_PAGE), b"trailing garbage", content_encoding=coding)

    # when
    body = await read_inflated_body(response, len(_PAGE) + 100)

    # then
    assert body == _PAGE


@pytest.mark.parametrize("coding", ["gzip", "deflate"])
async def test_bytes_after_the_end_of_the_stream_in_the_same_chunk_are_ignored(coding: str) -> None:
    # given
    response = _Streamed(_ENCODERS[coding](_PAGE) + b"trailing garbage", content_encoding=coding)

    # when
    body = await read_inflated_body(response, len(_PAGE) + 100)

    # then
    assert body == _PAGE


async def test_bytes_after_a_brotli_stream_in_the_same_chunk_are_corrupt_data() -> None:
    # given
    response = _Streamed(_ENCODERS["br"](_PAGE) + b"trailing garbage", content_encoding="br")

    # when / then
    with pytest.raises(ContentDecodingError):
        await read_inflated_body(response, len(_PAGE) + 100)


async def test_a_zlib_body_labelled_gzip_reads_back_whole() -> None:
    # given a server that sends a zlib stream with Content-Encoding gzip
    response = _Streamed(zlib.compress(_PAGE), content_encoding="gzip")

    # when
    body = await read_inflated_body(response, len(_PAGE))

    # then
    assert body == _PAGE


def test_gunzip_capped_still_refuses_a_zlib_stream() -> None:
    # when / then
    with pytest.raises(ContentDecodingError):
        gunzip_capped(zlib.compress(_PAGE), len(_PAGE))


@pytest.mark.parametrize("value", ["5, 5", "abc", "", "-1", "+5", "1_000", " 5", "9" * 20, "9" * 5000])
async def test_an_unreadable_content_length_counts_as_absent(value: str) -> None:
    # given
    response = _Streamed(b"body")
    response.headers = Headers([("Content-Length", value)])

    # when
    body = await read_inflated_body(response, 8)

    # then
    assert body == b"body"
    assert declared_content_length(response.headers) is None


def test_a_readable_content_length_is_its_number() -> None:
    # when
    declared = declared_content_length(Headers([("Content-Length", "12345")]))

    # then
    assert declared == 12345


async def _drain_whole(response: _Streamed, limit: int) -> bytes:
    pieces: list[bytes] = []
    await drain_inflated(response, limit, pieces.append, require_whole=True)

    return b"".join(pieces)


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_whole_file_passes_the_end_of_stream_check(coding: str) -> None:
    # given
    response = _Streamed(_ENCODERS[coding](_PAGE), content_encoding=coding)

    # when
    body = await _drain_whole(response, len(_PAGE))

    # then
    assert body == _PAGE


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_a_file_cut_short_fails_the_end_of_stream_check(coding: str) -> None:
    # given
    response = _Streamed(_ENCODERS[coding](_PAGE)[:-3], content_encoding=coding)

    # when / then
    with pytest.raises(ContentDecodingError, match="ends before"):
        await _drain_whole(response, len(_PAGE))


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_an_empty_coded_file_fails_the_end_of_stream_check(coding: str) -> None:
    # given
    response = _Streamed(content_encoding=coding)

    # when / then
    with pytest.raises(ContentDecodingError, match="ends before"):
        await _drain_whole(response, len(_PAGE))


async def test_a_plain_file_needs_no_end_of_stream() -> None:
    # given
    response = _Streamed(b"not compressed")

    # when
    body = await _drain_whole(response, _ROOM_FOR_SHORT_PAGE)

    # then
    assert body == b"not compressed"


async def test_stacked_codings_pass_the_end_of_stream_check_when_every_layer_is_whole() -> None:
    # given
    response = _Streamed(brotli.compress(gzip.compress(_PAGE)), content_encoding="gzip, br")

    # when
    body = await _drain_whole(response, len(_PAGE) + _ROOM_FOR_SHORT_PAGE)

    # then
    assert body == _PAGE


async def test_an_inner_layer_cut_short_fails_the_end_of_stream_check() -> None:
    # given the outer br layer is whole and the gzip inside it is cut
    response = _Streamed(brotli.compress(gzip.compress(_PAGE)[:-10]), content_encoding="gzip, br")

    # when / then
    with pytest.raises(ContentDecodingError, match="ends before"):
        await _drain_whole(response, len(_PAGE) + _ROOM_FOR_SHORT_PAGE)


_INCOMPRESSIBLE = random.Random(1).randbytes(64 * 1024)


@pytest.mark.parametrize("kept_bytes", [1, 8, 20, 4096, 32 * 1024])
async def test_a_zstd_file_cut_anywhere_fails_the_end_of_stream_check(kept_bytes: int) -> None:
    # given raw blocks, so a cut can fall inside a block, on its header or in the frame header
    compressed = zstandard.ZstdCompressor(level=1).compress(_INCOMPRESSIBLE)
    response = _Streamed(compressed[:kept_bytes], content_encoding="zstd")

    # when / then
    with pytest.raises(ContentDecodingError, match="ends before"):
        await _drain_whole(response, 2 * len(_INCOMPRESSIBLE))


async def test_a_zstd_file_of_two_frames_passes_the_end_of_stream_check() -> None:
    # given
    compressor = zstandard.ZstdCompressor()
    response = _Streamed(compressor.compress(_PAGE) + compressor.compress(b"second"), content_encoding="zstd")

    # when
    body = await _drain_whole(response, len(_PAGE) + _ROOM_FOR_SHORT_PAGE)

    # then
    assert body == _PAGE + b"second"


@pytest.mark.parametrize("coding", sorted(_ENCODERS))
async def test_an_empty_compressed_answer_is_an_empty_body(coding: str) -> None:
    # given
    response = _Streamed(content_encoding=coding)

    # when
    body = await read_inflated_body(response, 10)

    # then
    assert body == b""


async def test_more_wire_bytes_than_the_limit_answer_none_even_with_little_output() -> None:
    # given a stream of empty deflate blocks that never produces output
    wire = _ZLIB_HEADER + _EMPTY_STORED_DEFLATE_BLOCK * 100
    response = _Streamed(wire, content_encoding="deflate")

    # when
    body = await read_inflated_body(response, 64)

    # then
    assert body is None


async def test_a_stacked_layer_that_expands_past_the_limit_stops_with_nothing_left_to_output() -> None:
    # given a gzip layer of empty blocks, hidden under a brotli layer, that never produces output
    inner = _GZIP_HEADER + _EMPTY_STORED_DEFLATE_BLOCK * 400_000
    response = _Streamed(brotli.compress(inner), content_encoding="gzip, br")

    # when
    body = await read_inflated_body(response, 64 * 1024)

    # then
    assert body is None


async def test_a_declared_length_above_the_limit_answers_none_without_reading() -> None:
    # given
    response = _Streamed(b"x" * 11, content_length=11)

    # when
    body = await read_inflated_body(response, 10)

    # then
    assert body is None
    assert response.chunks_read == 0


async def test_a_zstd_frame_with_a_window_above_the_http_limit_is_refused() -> None:
    # given a frame that needs a 32 MiB window
    parameters = zstandard.ZstdCompressionParameters.from_level(3, window_log=25)
    wire = zstandard.ZstdCompressor(compression_params=parameters).compress(bytes(40 * 1024 * 1024))
    response = _Streamed(wire, content_encoding="zstd")

    # when / then
    with pytest.raises(ContentDecodingError):
        await read_inflated_body(response, 80 * 1024 * 1024)


@pytest.mark.parametrize(
    "chunks",
    [(b"x" * _MAX_BYTES,), (b"xxx", b"x" * (_MAX_BYTES - 3)), (b"x" * _MAX_BYTES, b"")],
)
async def test_body_exactly_max_bytes_long_is_read_whole_and_not_cut(chunks: tuple[bytes, ...]) -> None:
    # when
    body, cut = await read_inflated_prefix(_Streamed(*chunks), _MAX_BYTES)

    # then
    assert body == b"x" * _MAX_BYTES
    assert cut is False


@pytest.mark.parametrize(
    "chunks",
    [(b"x" * (_MAX_BYTES + 1),), (b"x" * _MAX_BYTES, b"y"), (b"xxx", b"x" * (_MAX_BYTES - 2))],
)
async def test_body_one_byte_over_max_bytes_is_cut_at_max_bytes(chunks: tuple[bytes, ...]) -> None:
    # when
    body, cut = await read_inflated_prefix(_Streamed(*chunks), _MAX_BYTES)

    # then
    assert body == b"x" * _MAX_BYTES
    assert cut is True


async def test_a_compressed_body_over_the_limit_keeps_the_inflated_prefix() -> None:
    # given
    response = _Streamed(gzip.compress(_PAGE), content_encoding="gzip")

    # when
    body, cut = await read_inflated_prefix(response, 100)

    # then
    assert body == _PAGE[:100]
    assert cut is True


def test_gunzip_capped_hands_the_inflater_one_bounded_step_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # given a body that does not compress, so its stream is many steps long
    payload = random.Random(7).randbytes(4 * capped_inflate._INFLATE_STEP_BYTES)
    body = gzip.compress(payload)
    inputs: list[int] = []
    real_factory = zlib.decompressobj

    class Spy:
        def __init__(self, wbits: int) -> None:
            self._real = real_factory(wbits)

        def decompress(self, data: bytes, max_length: int) -> bytes:
            inputs.append(len(data))
            return self._real.decompress(data, max_length)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

    monkeypatch.setattr(zlib, "decompressobj", Spy)

    # when
    inflated = gunzip_capped(body, len(payload))

    # then
    assert inflated == payload
    assert max(inputs) <= capped_inflate._INFLATE_STEP_BYTES


def test_gunzip_capped_inflates_a_stream_whose_output_fills_every_step() -> None:
    # given a long run of zeros, whose whole input is consumed long before its output is read
    payload = bytes(4 * 1024 * 1024)

    # when / then
    assert gunzip_capped(gzip.compress(payload), len(payload)) == payload


def test_gunzip_capped_stops_at_the_cap() -> None:
    # when / then
    assert gunzip_capped(gzip.compress(bytes(1024)), 100) is None


def test_gunzip_capped_refuses_a_stream_cut_before_its_trailer() -> None:
    # given
    cut = gzip.compress(b"x" * 1000)[:-4]

    # when / then
    with pytest.raises(ValueError, match="before its trailer"):
        gunzip_capped(cut, 1024)


def test_gunzip_capped_refuses_input_that_is_not_gzip() -> None:
    # when / then
    with pytest.raises(ValueError, match="not a valid gzip stream"):
        gunzip_capped(b"\x1f\x8b\x00not a deflate stream", 1024)
