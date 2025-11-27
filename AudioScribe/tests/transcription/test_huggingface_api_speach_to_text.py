from unittest.mock import patch, MagicMock

import pytest
from huggingface_hub.utils import HfHubHTTPError

from src.transcription.huggingface_api_speach_to_text import hf_transcript


@patch('src.transcription.huggingface_api_speach_to_text.open', new_callable=MagicMock)
@patch('src.transcription.huggingface_api_speach_to_text.AudioSegment')
@patch('src.transcription.huggingface_api_speach_to_text.InferenceClient')
def test_hf_transcript_with_chunking(mock_inference_client, mock_audio_segment, mock_open):
    mock_audio = MagicMock()
    mock_audio.__len__.return_value = 45 * 1000
    mock_audio_segment.from_file.return_value = mock_audio

    mock_client_instance = MagicMock()
    mock_client_instance.automatic_speech_recognition.side_effect = [
        {"text": "Part 1."},
        {"text": "Part 2."},
        {"text": "Part 3."},
    ]
    mock_inference_client.return_value = mock_client_instance

    result = hf_transcript("f", "f", "f")

    assert mock_client_instance.automatic_speech_recognition.call_count == 3
    assert result == "Part 1. Part 2. Part 3."


@patch('src.transcription.huggingface_api_speach_to_text.AudioSegment.from_file', side_effect=IOError("Pydub error"))
def test_hf_transcript_pydub_load_error(mock_from_file):
    with pytest.raises(IOError, match="Failed to load audio file for chunking"):
        hf_transcript("f", "f", "f")


@patch('src.transcription.huggingface_api_speach_to_text.open', new_callable=MagicMock)
@patch('src.transcription.huggingface_api_speach_to_text.AudioSegment')
@patch('src.transcription.huggingface_api_speach_to_text.InferenceClient')
def test_hf_transcript_api_error(mock_inference_client, mock_audio_segment, mock_open):
    mock_audio_segment.from_file.return_value.__len__.return_value = 10 * 1000
    mock_client_instance = MagicMock()
    mock_client_instance.automatic_speech_recognition.side_effect = HfHubHTTPError("Model not found")
    mock_inference_client.return_value = mock_client_instance

    with pytest.raises(ValueError, match="Hugging Face API failed to process an audio chunk"):
        hf_transcript("f", "f", "f")


@patch('src.transcription.huggingface_api_speach_to_text.os.environ.get', return_value=None)
def test_hf_transcript_no_token(mock_env):
    with pytest.raises(ValueError, match="HF_TOKEN environment variable not set!"):
        hf_transcript("f", "f", "f")


@patch('src.transcription.huggingface_api_speach_to_text.AudioSegment.from_file',
       side_effect=RuntimeError("Unexpected"))
def test_hf_transcript_generic_error(mock_from_file):
    # The application code catches the generic RuntimeError and re-raises it as an IOError
    with pytest.raises(IOError, match="Failed to load audio file for chunking"):
        hf_transcript("f", "f", "f")


@patch('src.transcription.huggingface_api_speach_to_text.os.remove')
@patch('src.transcription.huggingface_api_speach_to_text.AudioSegment')
@patch('src.transcription.huggingface_api_speach_to_text._transcribe_single_chunk', return_value="test text")
def test_hf_transcript_cleanup_error(mock_transcribe_chunk, mock_audio_segment, mock_remove):
    mock_remove.side_effect = OSError("Cleanup fail")
    mock_audio = MagicMock()
    mock_audio.__len__.return_value = 1000
    mock_audio_segment.from_file.return_value = mock_audio

    result = hf_transcript("f", "f", "f")
    assert result is not None
    mock_remove.assert_called()
