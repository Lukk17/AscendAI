from typing import Tuple, Generator, Any
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app

app = create_app()

client = TestClient(app)


@pytest.fixture
def mock_file() -> Tuple[str, bytes, str]:
    return "test.wav", b"fake audio data", "audio/wav"


@patch('src.api.rest.rest_endpoints.local_speech_transcription')
def test_transcribe_local_endpoint_with_timestamps(mock_local_transcription: MagicMock,
                                                   mock_file: Tuple[str, bytes, str]) -> None:
    async def fake_generator(*args: Any, **kwargs: Any) -> Generator[dict, None, None]:
        yield {'text': 'hello', 'start': 0, 'end': 1}

    mock_local_transcription.side_effect = fake_generator

    response = client.post(
        "/api/v1/transcribe/local",
        files={"file": mock_file},
        data={"with_timestamps": "true"}
    )

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "[0.00 - 1.00] hello" in response.text


@patch('src.api.rest.rest_endpoints.local_speech_transcription')
def test_transcribe_local_endpoint_without_timestamps(mock_local_transcription: MagicMock,
                                                      mock_file: Tuple[str, bytes, str]) -> None:
    async def fake_generator(*args: Any, **kwargs: Any) -> Generator[dict, None, None]:
        yield {'text': 'hello', 'start': 0, 'end': 0.5}
        yield {'text': 'world', 'start': 0.5, 'end': 1.0}

    mock_local_transcription.side_effect = fake_generator

    response = client.post(
        "/api/v1/transcribe/local",
        files={"file": mock_file},
        data={"with_timestamps": "false"}
    )

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "hello world" in response.text


@patch('src.api.rest.rest_endpoints.local_speech_transcription')
def test_transcribe_local_endpoint_generic_error(mock_local_transcription: MagicMock,
                                                 mock_file: Tuple[str, bytes, str]) -> None:
    async def fake_error_generator(*args: Any, **kwargs: Any) -> Generator[None, None, None]:
        raise RuntimeError("Generic unexpected error")
        yield

    mock_local_transcription.side_effect = fake_error_generator

    response = client.post("/api/v1/transcribe/local", files={"file": mock_file})

    assert response.status_code == 500
    assert "Generic unexpected error" in response.json()["detail"]


@patch('src.api.rest.rest_endpoints.openai_speech_transcription', side_effect=ValueError("Model not found"))
def test_transcribe_openai_endpoint_value_error(mock_openai_transcription: MagicMock,
                                                mock_file: Tuple[str, bytes, str]) -> None:
    response = client.post("/api/v1/transcribe/openai", files={"file": mock_file})

    assert response.status_code == 404
    assert "Model not found" in response.json()["detail"]


@patch('src.api.rest.rest_endpoints.hf_speech_transcription', side_effect=IOError("Corrupt audio file"))
def test_transcribe_hf_endpoint_io_error(mock_hf_transcription: MagicMock, mock_file: Tuple[str, bytes, str]) -> None:
    response = client.post("/api/v1/transcribe/hf", files={"file": mock_file})

    assert response.status_code == 400
    assert "Corrupt audio file" in response.json()["detail"]


@patch('src.api.rest.rest_endpoints.openai_speech_transcription')
def test_transcribe_openai_success(mock_openai_transcription: MagicMock, mock_file: Tuple[str, bytes, str]) -> None:
    mock_openai_transcription.return_value = "OpenAI Transcription"

    response = client.post("/api/v1/transcribe/openai", files={"file": mock_file})

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "OpenAI Transcription" in response.text


@patch('src.api.rest.rest_endpoints.openai_speech_transcription', side_effect=IOError("File Read Error"))
def test_transcribe_openai_io_error(mock_openai_transcription: MagicMock, mock_file: Tuple[str, bytes, str]) -> None:
    response = client.post("/api/v1/transcribe/openai", files={"file": mock_file})

    assert response.status_code == 400
    assert "File Read Error" in response.json()["detail"]


@patch('src.api.rest.rest_endpoints.openai_speech_transcription', side_effect=Exception("Critical Failure"))
def test_transcribe_openai_generic_error(mock_openai_transcription: MagicMock,
                                         mock_file: Tuple[str, bytes, str]) -> None:
    response = client.post("/api/v1/transcribe/openai", files={"file": mock_file})

    assert response.status_code == 500
    assert "Critical Failure" in response.json()["detail"]


@patch('src.api.rest.rest_endpoints.settings')
def test_transcribe_openai_missing_api_key(mock_settings: MagicMock, mock_file: Tuple[str, bytes, str]) -> None:
    mock_settings.OPENAI_API_KEY = None

    response = client.post("/api/v1/transcribe/openai", files={"file": mock_file})

    assert response.status_code == 500
    assert "OPENAI_API_KEY is not configured" in response.json()["detail"]


@patch('src.api.rest.rest_endpoints.hf_speech_transcription')
def test_transcribe_hf_success(mock_hf_transcription: MagicMock, mock_file: Tuple[str, bytes, str]) -> None:
    mock_hf_transcription.return_value = "HF Transcription"

    response = client.post("/api/v1/transcribe/hf", files={"file": mock_file})

    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "HF Transcription" in response.text


@patch('src.api.rest.rest_endpoints.hf_speech_transcription', side_effect=ValueError("Invalid Model"))
def test_transcribe_hf_value_error(mock_hf_transcription: MagicMock, mock_file: Tuple[str, bytes, str]) -> None:
    response = client.post("/api/v1/transcribe/hf", files={"file": mock_file})

    assert response.status_code == 404
    assert "Invalid Model" in response.json()["detail"]


@patch('src.api.rest.rest_endpoints.hf_speech_transcription', side_effect=Exception("HF Down"))
def test_transcribe_hf_generic_error(mock_hf_transcription: MagicMock, mock_file: Tuple[str, bytes, str]) -> None:
    response = client.post("/api/v1/transcribe/hf", files={"file": mock_file})

    assert response.status_code == 500
    assert "HF Down" in response.json()["detail"]


@patch('src.api.rest.rest_endpoints.settings')
def test_transcribe_hf_missing_token(mock_settings: MagicMock, mock_file: Tuple[str, bytes, str]) -> None:
    mock_settings.HF_TOKEN = None

    response = client.post("/api/v1/transcribe/hf", files={"file": mock_file})

    assert response.status_code == 500
    assert "HF_TOKEN is not configured" in response.json()["detail"]
