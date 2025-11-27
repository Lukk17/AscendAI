import os
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.io.download_service import download_to_temp_async


@pytest.mark.asyncio
async def test_download_file_uri_success(tmp_path):
    # Create a dummy source file
    source_file = tmp_path / "test_audio.wav"
    source_file.write_bytes(b"fake audio content")

    uri = source_file.as_uri()  # e.g. file:///path/to/test_audio.wav

    temp_path = await download_to_temp_async(uri)

    try:
        assert os.path.exists(temp_path)
        with open(temp_path, "rb") as f:
            content = f.read()
        assert content == b"fake audio content"
        assert temp_path.endswith(".wav")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.mark.asyncio
async def test_download_file_uri_not_found():
    uri = "file:///non/existent/path.wav"
    with pytest.raises(ValueError, match="File not found"):
        await download_to_temp_async(uri)


@pytest.mark.asyncio
async def test_download_http_uri_success():
    mock_content = b"http audio content"
    uri = "http://example.com/audio.mp3"

    # Mock aiohttp.ClientSession
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.read.return_value = mock_content

    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    # session.get() returns a context manager, NOT a coroutine, so it must be a MagicMock
    mock_session.get = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_response

    with patch("aiohttp.ClientSession", return_value=mock_session):
        temp_path = await download_to_temp_async(uri)

        try:
            assert os.path.exists(temp_path)
            with open(temp_path, "rb") as f:
                content = f.read()
            assert content == mock_content
            assert temp_path.endswith(".mp3")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


@pytest.mark.asyncio
async def test_download_http_uri_404():
    uri = "http://example.com/audio.mp3"

    mock_response = AsyncMock()
    mock_response.status = 404

    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    mock_session.get = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_response

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(ValueError, match="Failed to download from .* 404"):
            await download_to_temp_async(uri)


@pytest.mark.asyncio
async def test_download_http_uri_401():
    uri = "http://example.com/secret.mp3"

    mock_response = AsyncMock()
    mock_response.status = 401

    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    mock_session.get = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_response

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(ValueError, match="Failed to download from .* 401"):
            await download_to_temp_async(uri)


@pytest.mark.asyncio
async def test_download_http_uri_403():
    uri = "http://example.com/forbidden.mp3"

    mock_response = AsyncMock()
    mock_response.status = 403

    mock_session = MagicMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    mock_session.get = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_response

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(ValueError, match="Failed to download from .* 403"):
            await download_to_temp_async(uri)


@pytest.mark.asyncio
async def test_download_unsupported_scheme():
    uri = "ftp://example.com/file.wav"
    with pytest.raises(ValueError, match="Unsupported URI scheme: ftp"):
        await download_to_temp_async(uri)
