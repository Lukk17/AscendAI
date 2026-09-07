import io
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.exception_handlers import FileSizeExceededError
from src.api.mcp.mcp_server import ocr_process
from src.config.config import settings
from src.main import create_app
from tests.conftest import VALID_MULTI_PAGE_PDF_BYTES, VALID_PNG_BYTES


@pytest.fixture
async def rest_client():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestBothSurfacesRefuseTheSamePixelCeilingIdentically:
    async def test_oversized_image_refused_by_both_surfaces(self, rest_client, tmp_path: Path, monkeypatch):
        # Given — a ceiling too small for the fixture image, on both surfaces at once
        monkeypatch.setattr(settings, "OCR_MAX_INFERENCE_PIXELS", 10)

        # When — REST
        with patch("src.api.rest.rest_endpoints.dispatch_ocr_request") as rest_dispatch:
            rest_response = await rest_client.post(
                "/v1/ocr",
                files={"file": ("test.png", io.BytesIO(VALID_PNG_BYTES), "image/png")},
            )

        # When — MCP, via a jailed file:// URI
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        image_path = tmp_path / "scan.png"
        image_path.write_bytes(VALID_PNG_BYTES)
        with (
            patch("src.api.mcp.mcp_server.dispatch_ocr_request") as mcp_dispatch,
            pytest.raises(FileSizeExceededError, match="FILE_TOO_LARGE") as mcp_exc_info,
        ):
            await ocr_process(image_path.as_uri(), lang="en")

        # Then — same code, neither surface ever touched the worker
        assert rest_response.status_code == 400
        assert rest_response.json()["code"] == "FILE_TOO_LARGE"
        assert "FILE_TOO_LARGE" in str(mcp_exc_info.value)
        rest_dispatch.assert_not_called()
        mcp_dispatch.assert_not_called()


class TestBothSurfacesRefuseTheSamePageLimitIdentically:
    async def test_document_over_page_limit_refused_by_both_surfaces(self, rest_client, tmp_path: Path, monkeypatch):
        # Given — floor(1.0 / 1.0) == 1 page allowed, the fixture PDF has two
        monkeypatch.setattr(settings, "OCR_REQUEST_TIMEOUT", 1.0)
        monkeypatch.setattr(settings, "OCR_PAGE_TIMEOUT_SECONDS", 1.0)

        # When — REST
        with patch("src.api.rest.rest_endpoints.dispatch_ocr_request") as rest_dispatch:
            rest_response = await rest_client.post(
                "/v1/ocr",
                files={"file": ("doc.pdf", io.BytesIO(VALID_MULTI_PAGE_PDF_BYTES), "application/pdf")},
            )

        # When — MCP, via a jailed file:// URI
        monkeypatch.setattr(settings, "MCP_FILE_URI_ROOT", str(tmp_path))
        doc_path = tmp_path / "doc.pdf"
        doc_path.write_bytes(VALID_MULTI_PAGE_PDF_BYTES)
        with (
            patch("src.api.mcp.mcp_server.dispatch_ocr_request") as mcp_dispatch,
            pytest.raises(FileSizeExceededError, match="FILE_TOO_LARGE") as mcp_exc_info,
        ):
            await ocr_process(doc_path.as_uri(), lang="en")

        # Then
        assert rest_response.status_code == 400
        assert rest_response.json()["code"] == "FILE_TOO_LARGE"
        assert "FILE_TOO_LARGE" in str(mcp_exc_info.value)
        rest_dispatch.assert_not_called()
        mcp_dispatch.assert_not_called()
