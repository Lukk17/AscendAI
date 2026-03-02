import os
import pytest
import tempfile
from src.model.ocr_models import OcrJsonResponse, OcrPageResult, OcrTextLine
from unittest.mock import patch, MagicMock


class TestOcrProcessTool:
    @patch("src.api.mcp.mcp_server.ocr_service")
    async def test_successful_ocr_process(self, mock_service):
        # Arrange
        from src.api.mcp.mcp_server import ocr_process

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"fake_image_data")
            tmp_path = tmp.name

        expected_filename: str = os.path.basename(tmp_path)
        mock_line = OcrTextLine(
            text="Test", confidence=0.9,
            bounding_box=[[0, 0], [100, 0], [100, 20], [0, 20]],
        )
        mock_response = OcrJsonResponse(
            filename=expected_filename, language="en",
            pages=[OcrPageResult(page_number=1, lines=[mock_line])],
            processing_time_seconds=0.5,
        )
        mock_service.process_file.return_value = mock_response

        try:
            # Act
            result = await ocr_process(tmp_path, lang="en")

            # Assert
            assert result["filename"] == expected_filename
            assert result["language"] == "en"
            mock_service.process_file.assert_called_once()
        finally:
            os.unlink(tmp_path)

    async def test_file_not_found_raises(self):
        # Arrange
        from src.api.mcp.mcp_server import ocr_process

        # Act / Assert
        with pytest.raises(FileNotFoundError):
            await ocr_process("/nonexistent/path/file.png")
