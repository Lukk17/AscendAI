from unittest.mock import AsyncMock, patch

import pytest

from src.reader.web_reader import WebReader


@pytest.mark.asyncio
async def test_web_reader_success_first_strategy():
    mock_content = "Extracted Content"

    with patch("src.reader.web_reader.TrafilaturaStrategy.extract", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = mock_content

        with patch("src.reader.web_reader.ContentValidator.validate", return_value=True):
            reader = WebReader()
            result = await reader.read("http://test.com")

            assert result["status"] == "success"
            assert result["content"] == mock_content
            assert "1-trafilatura" in result["method"]


@pytest.mark.asyncio
async def test_web_reader_all_strategies_fail():
    with patch("src.reader.web_reader.WebReader._execute_strategy", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = None

        reader = WebReader()
        result = await reader.read("http://fail.com")

        assert result["status"] == "error"


@pytest.mark.asyncio
async def test_web_reader_read_with_links_uses_strategy_chain():
    raw_html = "<html><body><a href='https://example.com/job1'>Job One</a></body></html>"

    with patch("src.reader.web_reader.TrafilaturaStrategy.get_html", new_callable=AsyncMock) as mock_get_html:
        mock_get_html.return_value = raw_html

        reader = WebReader()
        result = await reader.read_with_links("http://test.com")

        assert result["status"] == "success"
        assert "content" in result
        assert "links" in result
        assert 1 in result["links"]
        assert result["links"][1] == "https://example.com/job1"


@pytest.mark.asyncio
async def test_web_reader_read_with_links_and_filter():
    raw_html = """
    <html><body>
        <a href='https://example.com/job-offer/senior'>Senior</a>
        <a href='https://example.com/about'>About</a>
    </body></html>
    """

    with patch("src.reader.web_reader.TrafilaturaStrategy.get_html", new_callable=AsyncMock) as mock_get_html:
        mock_get_html.return_value = raw_html

        reader = WebReader()
        result = await reader.read_with_links("http://test.com", link_filter="/job-offer/")

        assert len(result["links"]) == 1
        assert result["links"][1] == "https://example.com/job-offer/senior"


@pytest.mark.asyncio
async def test_web_reader_read_with_links_escalates_on_empty_html():
    raw_html = "<html><body><a href='https://example.com/job1'>Job</a></body></html>"

    with patch("src.reader.web_reader.TrafilaturaStrategy.get_html", new_callable=AsyncMock) as mock_first:
        mock_first.return_value = ""

        with patch("src.reader.web_reader.PlaywrightStrategy.get_html", new_callable=AsyncMock) as mock_second:
            mock_second.return_value = raw_html

            reader = WebReader()
            result = await reader.read_with_links("http://test.com")

            assert result["status"] == "success"
            mock_first.assert_called_once()
            mock_second.assert_called_once()


@pytest.mark.asyncio
async def test_web_reader_read_with_links_all_strategies_fail():
    with patch("src.reader.web_reader.WebReader._execute_html_strategy", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = ""

        reader = WebReader()
        result = await reader.read_with_links("http://fail.com")

        assert result["status"] == "error"
