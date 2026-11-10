"""Bounded reads of compressed HTTP bodies.

The bodies read here come off the wire undecoded, and each is inflated in
Python according to its Content-Encoding (gzip, deflate, br, zstd), with
output bounded in pieces and the read stopped at the limit. ``gunzip_capped``
is the same capped inflation for a gzip file that is already in memory.
"""

import zlib
from collections.abc import Callable, Mapping
from contextlib import aclosing
from typing import IO, Any, Final, Protocol, cast

import brotli
import zstandard

_INFLATE_STEP_BYTES: Final[int] = 64 * 1024
_ZSTD_MAX_WINDOW_BYTES: Final[int] = 8 * 1024 * 1024
_MAX_STACKED_CODINGS: Final[int] = 5
_PLAIN_CODINGS: Final[frozenset[str]] = frozenset({"identity", "none"})
_CONTENT_ENCODING: Final[str] = "content-encoding"
_CONTENT_LENGTH: Final[str] = "content-length"
_MAX_CONTENT_LENGTH_DIGITS: Final[int] = 19

_GZIP_WBITS: Final[int] = zlib.MAX_WBITS | 16
_GZIP_OR_ZLIB_WBITS: Final[int] = zlib.MAX_WBITS | 32
_ZLIB_WBITS: Final[int] = zlib.MAX_WBITS
_RAW_DEFLATE_WBITS: Final[int] = -zlib.MAX_WBITS
_ZLIB_HEADER_BYTES: Final[int] = 2
_ZLIB_METHOD_MASK: Final[int] = 0x0F
_ZLIB_DEFLATE_METHOD: Final[int] = 8
_ZLIB_HEADER_CHECK: Final[int] = 31
_BYTE_SHIFT: Final[int] = 256
_ZSTD_END_PROBE_TEXT: Final[bytes] = b"end of stream probe"
_ZSTD_END_PROBE_FRAME: Final[bytes] = zstandard.ZstdCompressor().compress(_ZSTD_END_PROBE_TEXT)

PieceWriter = Callable[[bytes], object]


class BodyOverLimitError(Exception):
    """The body delivered or inflated to more bytes than its limit allows."""


class ContentDecodingError(ValueError):
    """The body cannot be decoded: a coding that is not supported, or corrupt data."""


class _Decoder(Protocol):
    def feed(self, data: bytes) -> None: ...

    def ended_whole(self) -> bool: ...


class _ZlibDecoder:
    def __init__(self, wbits: int, emit: PieceWriter, coding: str) -> None:
        self._inflater = zlib.decompressobj(wbits)
        self._emit = emit
        self._coding = coding

    def ended_whole(self) -> bool:
        return self._inflater.eof

    def feed(self, data: bytes) -> None:
        pending = data
        while not self._inflater.eof:
            try:
                piece = self._inflater.decompress(pending, _INFLATE_STEP_BYTES)
            except zlib.error as exc:
                raise ContentDecodingError(f"not a valid {self._coding} stream: {exc}") from exc
            if piece:
                self._emit(piece)
            pending = self._inflater.unconsumed_tail
            if not pending and len(piece) < _INFLATE_STEP_BYTES:
                return


class _DeflateDecoder:
    def __init__(self, emit: PieceWriter) -> None:
        self._emit = emit
        self._head = b""
        self._inner: _ZlibDecoder | None = None

    def feed(self, data: bytes) -> None:
        if self._inner is None:
            self._head += data
            if len(self._head) < _ZLIB_HEADER_BYTES:
                return
            wbits = _ZLIB_WBITS if _has_zlib_header(self._head) else _RAW_DEFLATE_WBITS
            self._inner = _ZlibDecoder(wbits, self._emit, "deflate")
            data, self._head = self._head, b""
        self._inner.feed(data)

    def ended_whole(self) -> bool:
        return self._inner is not None and self._inner.ended_whole()


class _BrotliDecoder:
    def __init__(self, emit: PieceWriter) -> None:
        self._decoder = brotli.Decompressor()
        self._emit = emit

    def feed(self, data: bytes) -> None:
        pending = data
        while not self._decoder.is_finished():
            try:
                piece = self._decoder.process(pending, output_buffer_limit=_INFLATE_STEP_BYTES)
            except brotli.error as exc:
                raise ContentDecodingError(f"not a valid br stream: {exc}") from exc
            if not piece:
                return
            self._emit(piece)
            pending = b""

    def ended_whole(self) -> bool:
        return bool(self._decoder.is_finished())


class _PieceSink:
    def __init__(self, emit: PieceWriter) -> None:
        self.emit = emit

    def write(self, data: bytes) -> int:
        self.emit(data)

        return len(data)


class _ZstdDecoder:
    def __init__(self, emit: PieceWriter) -> None:
        self._sink = _PieceSink(emit)
        self._writer = zstandard.ZstdDecompressor(max_window_size=_ZSTD_MAX_WINDOW_BYTES).stream_writer(
            cast("IO[bytes]", self._sink),
            write_size=_INFLATE_STEP_BYTES,
            write_return_read=True,
        )
        self._started = False

    def feed(self, data: bytes) -> None:
        self._started = True
        try:
            self._writer.write(data)
        except zstandard.ZstdError as exc:
            raise ContentDecodingError(f"not a valid zstd stream: {exc}") from exc

    def ended_whole(self) -> bool:
        """Answer whether the input stopped between frames, where a probe frame decodes to its own text."""
        heard: list[bytes] = []
        self._sink.emit = heard.append
        try:
            self._writer.write(_ZSTD_END_PROBE_FRAME)
        except zstandard.ZstdError:
            return False

        return self._started and b"".join(heard) == _ZSTD_END_PROBE_TEXT


def _gzip_decoder(emit: PieceWriter) -> _Decoder:
    return _ZlibDecoder(_GZIP_OR_ZLIB_WBITS, emit, "gzip")


_DECODERS: Final[Mapping[str, Callable[[PieceWriter], _Decoder]]] = {
    "gzip": _gzip_decoder,
    "x-gzip": _gzip_decoder,
    "deflate": _DeflateDecoder,
    "br": _BrotliDecoder,
    "zstd": _ZstdDecoder,
}


def _has_zlib_header(head: bytes) -> bool:
    first, second = head[0], head[1]

    return (first & _ZLIB_METHOD_MASK) == _ZLIB_DEFLATE_METHOD and (
        first * _BYTE_SHIFT + second
    ) % _ZLIB_HEADER_CHECK == 0


def _limited_writer(max_bytes: int, write: PieceWriter) -> PieceWriter:
    total = 0

    def limited(piece: bytes) -> None:
        nonlocal total
        room = max_bytes - total
        if len(piece) > room:
            write(piece[:room])
            raise BodyOverLimitError
        total += len(piece)
        write(piece)

    return limited


def _chain_for(
    content_encoding: str | None, max_bytes: int, write: PieceWriter
) -> tuple[PieceWriter, list[_Decoder]]:
    names = (part.strip().lower() for part in (content_encoding or "").split(","))
    codings = [name for name in names if name and name not in _PLAIN_CODINGS]
    if len(codings) > _MAX_STACKED_CODINGS:
        raise ContentDecodingError(f"too many stacked content codings: {len(codings)}")
    head = _limited_writer(max_bytes, write)
    decoders: list[_Decoder] = []
    for coding in codings:
        factory = _DECODERS.get(coding)
        if factory is None:
            raise ContentDecodingError(f"unsupported content coding: {coding}")
        decoder = factory(head)
        decoders.append(decoder)
        head = _limited_writer(max_bytes, decoder.feed)

    return head, decoders


def declared_content_length(headers: Any) -> int | None:
    """Answer the Content-Length of *headers*, or None when it is absent or unreadable."""
    declared: str | None = headers.get(_CONTENT_LENGTH)
    if declared is None or not declared.isdecimal() or len(declared) > _MAX_CONTENT_LENGTH_DIGITS:
        return None

    return int(declared)


async def drain_inflated(
    response: Any, max_bytes: int, write: PieceWriter, *, require_whole: bool = False
) -> None:
    """Stream *response*, inflate it per its Content-Encoding and pass every piece to *write*.

    Stops at *max_bytes*, counted on the wire bytes and on the output of every decoding layer.
    With *require_whole* set, every content coding must also reach its end of stream.

    Raises:
        BodyOverLimitError: when the body passes *max_bytes*, after *write* got the bytes up to it.
        ContentDecodingError: when the coding is not supported, the data is corrupt, or a coding ends early.
    """
    feed, decoders = _chain_for(response.headers.get(_CONTENT_ENCODING), max_bytes, write)
    async with aclosing(response.aiter_content()) as stream:
        async for chunk in stream:
            feed(bytes(chunk))
    if require_whole and not all(decoder.ended_whole() for decoder in decoders):
        raise ContentDecodingError("the body ends before its content coding does")


async def read_inflated_body(response: Any, max_bytes: int) -> bytes | None:
    """Read and inflate a streamed body whole, or None when its declared length or size passes *max_bytes*.

    Raises:
        ContentDecodingError: when the coding is not supported or the data is corrupt.
    """
    declared = declared_content_length(response.headers)
    if declared is not None and declared > max_bytes:
        return None

    pieces: list[bytes] = []
    try:
        await drain_inflated(response, max_bytes, pieces.append)
    except BodyOverLimitError:
        return None

    return b"".join(pieces)


async def read_inflated_prefix(response: Any, max_bytes: int) -> tuple[bytes, bool]:
    """Read and inflate a streamed body up to *max_bytes*, answering the bytes and whether more came.

    Raises:
        ContentDecodingError: when the coding is not supported or the data is corrupt.
    """
    pieces: list[bytes] = []
    try:
        await drain_inflated(response, max_bytes, pieces.append)
    except BodyOverLimitError:
        return b"".join(pieces), True

    return b"".join(pieces), False


def gunzip_capped(compressed: bytes, max_bytes: int) -> bytes | None:
    """Inflate one gzip stream in bounded steps, or None once the output passes *max_bytes*.

    Raises:
        ContentDecodingError: when *compressed* is not one whole gzip stream.
    """
    inflated = bytearray()
    decoder = _ZlibDecoder(_GZIP_WBITS, _limited_writer(max_bytes, inflated.extend), "gzip")
    try:
        for start in range(0, len(compressed), _INFLATE_STEP_BYTES):
            decoder.feed(compressed[start : start + _INFLATE_STEP_BYTES])
    except BodyOverLimitError:
        return None
    if not decoder.ended_whole():
        raise ContentDecodingError("the gzip stream ends before its trailer")

    return bytes(inflated)
