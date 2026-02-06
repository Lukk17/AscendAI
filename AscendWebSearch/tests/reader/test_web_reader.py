from unittest.mock import AsyncMock, patch

import pytest

from src.reader.web_reader import WebReader


@pytest.mark.asyncio
async def test_web_reader_success_first_strategy():
    mock_content = "Extracted Content"

    # Mock the first strategy (Trafilatura)
    with patch("src.reader.web_reader.TrafilaturaStrategy.extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = mock_content

        # Ensure validation passes
        with patch("src.reader.web_reader.ContentValidator.validate", return_value=True):
            reader = WebReader()
            result = await reader.read("http://test.com")

            assert result["status"] == "success"
            assert result["content"] == mock_content
            # Implementation specific: it iterates dict, so order matters. Trafilatura is usually first.
            assert "1-trafilatura" in result["method"]


@pytest.mark.asyncio
async def test_web_reader_all_strategies_fail():
    # Mock _execute_strategy to verify fallback loop
    with patch("src.reader.web_reader.WebReader._execute_strategy", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = None

        reader = WebReader()
        result = await reader.read("http://fail.com")

        assert result["status"] == "error"
