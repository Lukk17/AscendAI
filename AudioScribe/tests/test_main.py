import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from main import app

client = TestClient(app)


@pytest.fixture
def mock_file():
    return "test.wav", b"fake audio data", "audio/wav"


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to the AudioScribe API"}


@patch('main.local_speech_transcription')
def test_transcribe_local_endpoint_with_timestamps(mock_local_transcription, mock_file):
    async def fake_generator(*args, **kwargs):
        yield {'text': 'hello', 'start': 0, 'end': 1}

    mock_local_transcription.side_effect = fake_generator

    response = client.post(
        "/api/v1/transcribe/local",
        files={"file": mock_file},
        data={"with_timestamps": "true"}
    )
    assert response.status_code == 200
    json_response = response.json()
    assert len(json_response["transcription"]) == 1


@patch('main.local_speech_transcription')
def test_transcribe_local_endpoint_without_timestamps(mock_local_transcription, mock_file):
    async def fake_generator(*args, **kwargs):
        yield {'text': 'hello'}
        yield {'text': 'world'}

    mock_local_transcription.side_effect = fake_generator

    response = client.post(
        "/api/v1/transcribe/local",
        files={"file": mock_file},
        data={"with_timestamps": "false"}
    )
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["transcription"] == "hello world"


@patch('main.local_speech_transcription')
def test_transcribe_local_endpoint_generic_error(mock_local_transcription, mock_file):
    async def fake_error_generator(*args, **kwargs):
        raise RuntimeError("Generic unexpected error")
        yield

    mock_local_transcription.side_effect = fake_error_generator

    response = client.post("/api/v1/transcribe/local", files={"file": mock_file})
    assert response.status_code == 500
    assert "Generic unexpected error" in response.json()["detail"]


@patch('main.openai_speech_transcription', side_effect=ValueError("Model not found"))
def test_transcribe_openai_endpoint_value_error(mock_openai_transcription, mock_file):
    response = client.post("/api/v1/transcribe/openai", files={"file": mock_file})
    assert response.status_code == 404
    assert "Model not found" in response.json()["detail"]


@patch('main.hf_speech_transcription', side_effect=IOError("Corrupt audio file"))
def test_transcribe_hf_endpoint_io_error(mock_hf_transcription, mock_file):
    response = client.post("/api/v1/transcribe/hf", files={"file": mock_file})
    assert response.status_code == 400
    assert "Corrupt audio file" in response.json()["detail"]
