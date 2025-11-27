from unittest.mock import patch

import pytest

from src.scribe import (
    openai_speech_transcription,
    hf_speech_transcription,
    local_speech_transcription
)


@patch('src.scribe.openai_transcript', return_value="OpenAI text")
def test_openai_speech_transcription_calls_correct_function(mock_openai_transcript):
    result = openai_speech_transcription("fake_path.wav", "whisper-1", "en")

    mock_openai_transcript.assert_called_once_with("fake_path.wav", "whisper-1", "en")
    assert result == "OpenAI text"


@patch('src.scribe.hf_transcript', return_value="HF text")
def test_hf_speech_transcription_calls_correct_function(mock_hf_transcript):
    result = hf_speech_transcription("fake_path.wav", "some/model", "hf-inference")

    mock_hf_transcript.assert_called_once_with("fake_path.wav", "some/model", "hf-inference")
    assert result == "HF text"


@pytest.mark.asyncio
@patch('src.scribe.local_speech_transcription_stream')
async def test_local_speech_transcription_calls_correct_function(mock_local_stream):
    async def fake_generator():
        yield {"text": "test"}

    mock_local_stream.return_value = fake_generator()

    results = [segment async for segment in local_speech_transcription(
        "fake_path.wav", "fake/model", "en"
    )]

    mock_local_stream.assert_called_once_with("fake/model", "fake_path.wav", "en")
    assert len(results) == 1
    assert results[0]["text"] == "test"
