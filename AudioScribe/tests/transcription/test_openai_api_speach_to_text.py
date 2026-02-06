from unittest.mock import patch, MagicMock

import pytest
from openai import APIError

from src.transcription.openai_api_speach_to_text import openai_transcript


class MockTranscription:
    def __init__(self, text):
        self.text = text


@patch('src.transcription.openai_api_speach_to_text.open', new_callable=MagicMock)
@patch('src.transcription.openai_api_speach_to_text.os.path.getsize')
@patch('src.transcription.openai_api_speach_to_text.AudioSegment')
@patch('src.transcription.openai_api_speach_to_text.client')
def test_openai_transcript_with_chunking(mock_client, mock_audio, mock_getsize, mock_open):
    # First call: input file (30MB) -> triggers chunking
    # Subsequent calls: chunks (10MB) -> pass fail-safe check
    mock_getsize.side_effect = [30 * 1024 * 1024, 10 * 1024 * 1024, 10 * 1024 * 1024, 10 * 1024 * 1024]

    # Configure mock audio to support fluent interface for normalization
    mock_audio_instance = MagicMock()
    # At 32KB/sec, 20MB is ~655 seconds. We need > 655s to trigger chunking.
    # Let's set it to 700 seconds (700,000 ms). 
    mock_audio_instance.__len__.return_value = 700 * 1000
    mock_audio_instance.set_frame_rate.return_value = mock_audio_instance
    mock_audio_instance.set_channels.return_value = mock_audio_instance
    mock_audio_instance.set_sample_width.return_value = mock_audio_instance

    mock_audio.from_file.return_value = mock_audio_instance

    mock_client.audio.transcriptions.create.side_effect = [MockTranscription("1"), MockTranscription("2")]

    result = openai_transcript("f", "f", "en")
    assert mock_client.audio.transcriptions.create.call_count == 2
    assert result == "1 2"


@patch('src.transcription.openai_api_speach_to_text.open', new_callable=MagicMock)
@patch('src.transcription.openai_api_speach_to_text.os.path.getsize')
@patch('src.transcription.openai_api_speach_to_text.client')
def test_openai_transcript_without_chunking(mock_client, mock_getsize, mock_open):
    mock_getsize.return_value = 10 * 1024 * 1024
    mock_client.audio.transcriptions.create.return_value = MockTranscription("Full")

    result = openai_transcript("f", "f", "en")
    assert mock_client.audio.transcriptions.create.call_count == 1
    assert result == "Full"


@patch('src.transcription.openai_api_speach_to_text.os.path.getsize', return_value=30e6)
@patch('src.transcription.openai_api_speach_to_text.AudioSegment.from_file', side_effect=IOError("Pydub error"))
def test_openai_transcript_pydub_error(mock_from_file, mock_getsize):
    with pytest.raises(IOError, match="Failed to load audio file"):
        openai_transcript("f", "f", "en")


@patch('src.transcription.openai_api_speach_to_text.open', new_callable=MagicMock)
@patch('src.transcription.openai_api_speach_to_text.os.path.getsize', return_value=10e6)
@patch('src.transcription.openai_api_speach_to_text.client')
def test_openai_transcript_api_error(mock_client, mock_getsize, mock_open):
    mock_client.audio.transcriptions.create.side_effect = APIError("key", request=MagicMock(), body=None)
    with pytest.raises(ValueError, match="failed to process"):
        openai_transcript("f", "f", "en")
