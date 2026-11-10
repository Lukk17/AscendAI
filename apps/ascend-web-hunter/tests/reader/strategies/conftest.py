import codecs
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def make_streaming(response: Any, body: str | bytes = b"") -> Any:
    """Make a fake curl_cffi answer stream *body* the way a streamed response does."""
    data = body.encode("utf-8") if isinstance(body, str) else body

    async def aiter_content() -> AsyncIterator[bytes]:
        yield data

    response.aiter_content = aiter_content
    response.quit_now = MagicMock()
    response.aclose = AsyncMock()

    return response


@dataclass(frozen=True, slots=True)
class HostileCodec:
    name: str
    decode: MagicMock


@pytest.fixture
def hostile_codec() -> Iterator[HostileCodec]:
    codec = HostileCodec("hostilecodec", MagicMock(return_value=("decoded by the hostile codec", 0)))
    info = codecs.CodecInfo(encode=MagicMock(), decode=codec.decode, name=codec.name)

    def search(name: str) -> codecs.CodecInfo | None:
        return info if name == codec.name else None

    codecs.register(search)
    yield codec
    codecs.unregister(search)
