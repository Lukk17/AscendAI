import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.io.file_service import safe_suffix_from_filename, cleanup_temp_file, save_upload_to_temp_async, \
    create_temp_file


# noinspection PyProtectedMember
@pytest.mark.parametrize("filename, expected_suffix", [
    ("test.wav", ".wav"),
    ("archive.tar.gz", ".gz"),
    ("no_extension", ""),
    (None, ""),
    ("", ""),
    (12345, ""),  # Test invalid type to cover the except block
])
def test_safe_suffix_from_filename(filename, expected_suffix):
    assert safe_suffix_from_filename(filename) == expected_suffix


@patch('os.path.exists')
@patch('os.remove')
def test_cleanup_temp_file_exists(mock_remove, mock_exists):
    mock_exists.return_value = True
    file_path = "/fake/path/file.tmp"
    cleanup_temp_file(file_path)
    mock_exists.assert_called_once_with(file_path)
    mock_remove.assert_called_once_with(file_path)


@patch('os.path.exists')
@patch('os.remove')
def test_cleanup_temp_file_not_exists(mock_remove, mock_exists):
    mock_exists.return_value = False
    file_path = "/fake/path/file.tmp"
    cleanup_temp_file(file_path)
    mock_exists.assert_called_once_with(file_path)
    mock_remove.assert_not_called()


@patch('os.remove', side_effect=OSError("Permission Denied"))
@patch('os.path.exists', return_value=True)
def test_cleanup_temp_file_handles_os_error(mock_exists, mock_remove):
    file_path = "/fake/path/file.tmp"
    try:
        cleanup_temp_file(file_path)
    except OSError:
        pytest.fail("cleanup_temp_file should handle OSError and not re-raise it.")
    mock_remove.assert_called_once_with(file_path)


@pytest.mark.asyncio
@patch('src.io.file_service._create_temp_file', return_value="/fake/temp/file.wav")
@patch('aiofiles.open')
async def test_save_upload_to_temp_async(mock_aio_open, mock_create_temp):
    async_file_mock = AsyncMock()
    mock_aio_open.return_value.__aenter__.return_value = async_file_mock

    mock_upload_file = MagicMock()
    mock_upload_file.filename = "test.wav"
    mock_upload_file.read = AsyncMock(return_value=b"fake audio data")
    mock_upload_file.seek = AsyncMock()

    temp_path = await save_upload_to_temp_async(mock_upload_file)

    # noinspection PyProtectedMember
    mock_create_temp.assert_called_once_with(".wav")
    assert temp_path == "/fake/temp/file.wav"
    mock_upload_file.seek.assert_awaited_once_with(0)
    mock_aio_open.assert_called_once_with("/fake/temp/file.wav", 'wb')
    async_file_mock.write.assert_awaited_once_with(b"fake audio data")


def test_create_temp_file_creates_real_file():
    temp_path = None
    try:
        # noinspection PyProtectedMember
        temp_path = create_temp_file(suffix=".tmp")
        assert os.path.exists(temp_path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
