from unittest.mock import patch, MagicMock

import pytest

from src.transcription.local_speech_to_text import local_speech_transcription_stream, _transcribe_and_communicate


@pytest.mark.asyncio
@patch('src.transcription.local_speech_to_text.mp.get_context')
async def test_local_speech_transcription_stream_success(mock_get_context):
    mock_queue = MagicMock()
    mock_queue.get.return_value = [{'text': 'Hello'}]
    mock_process_instance = MagicMock()
    mock_context = MagicMock()
    mock_context.Queue.return_value = mock_queue
    mock_context.Process.return_value = mock_process_instance
    mock_get_context.return_value = mock_context

    results = [s async for s in local_speech_transcription_stream("f", "f", "en")]

    mock_context.Process.assert_called_once()
    assert len(results) == 1


@pytest.mark.asyncio
@patch('src.transcription.local_speech_to_text.mp.get_context')
async def test_local_speech_transcription_stream_worker_error(mock_get_context):
    mock_queue = MagicMock()
    mock_queue.get.return_value = ValueError("Worker Error")
    mock_context = MagicMock()
    mock_context.Queue.return_value = mock_queue
    mock_get_context.return_value = mock_context

    with pytest.raises(ValueError, match="Worker Error"):
        _ = [s async for s in local_speech_transcription_stream("f", "f", "en")]


@patch('src.transcription.local_speech_to_text.setup_logging')
@patch('src.transcription.local_speech_to_text.torch.cuda.is_available', return_value=False)
@patch('src.transcription.local_speech_to_text.WhisperModel')
@patch('src.transcription.local_speech_to_text.AudioSegment')
def test_worker_cpu_path(mock_audio_segment, mock_whisper, mock_cuda_check, mock_logging):
    mock_queue = MagicMock()
    mock_event = MagicMock()
    mock_whisper.return_value.transcribe.return_value = ([], None)
    mock_audio_segment.from_file.return_value.__len__.return_value = 1

    # noinspection PyProtectedMember
    _transcribe_and_communicate("f", "f", "en", mock_queue, mock_event)

    mock_cuda_check.assert_called_once()
    mock_whisper.assert_called_with("f", device="cpu", compute_type="int8")


@patch('src.transcription.local_speech_to_text.setup_logging')
@patch('src.transcription.local_speech_to_text.WhisperModel', side_effect=Exception("Model Load Fail"))
def test_worker_internal_exception(mock_whisper, mock_logging):
    mock_queue = MagicMock()
    mock_event = MagicMock()

    # noinspection PyProtectedMember
    _transcribe_and_communicate("f", "f", "en", mock_queue, mock_event)

    mock_queue.put.assert_called_once()
    assert isinstance(mock_queue.put.call_args[0][0], Exception)


@patch('src.transcription.local_speech_to_text.setup_logging')
@patch('src.transcription.local_speech_to_text.WhisperModel')
@patch('src.transcription.local_speech_to_text.AudioSegment')
@patch('src.transcription.local_speech_to_text.os.remove', side_effect=OSError("Cleanup fail"))
def test_worker_cleanup_os_error(mock_remove, mock_audio, mock_whisper, mock_logging):
    mock_queue = MagicMock()
    mock_event = MagicMock()
    mock_whisper.return_value.transcribe.return_value = ([], None)
    mock_audio.from_file.return_value.__len__.return_value = 1

    try:
        # noinspection PyProtectedMember
        _transcribe_and_communicate("f", "f", "en", mock_queue, mock_event)
    except OSError:
        pytest.fail("OSError during cleanup should not propagate")

    mock_remove.assert_called()
