from src.model.ocr_models import OcrJsonResponse, OcrPageResult, OcrTextLine


class OcrResponseFactory:
    @staticmethod
    def with_single_line(
        filename: str = "test.png",
        language: str = "en",
        text: str = "Test",
        confidence: float = 0.9,
    ) -> OcrJsonResponse:
        line = OcrTextLine(
            text=text,
            confidence=confidence,
            bounding_box=[[0.0, 0.0], [100.0, 0.0], [100.0, 20.0], [0.0, 20.0]],
        )

        return OcrJsonResponse(
            filename=filename,
            language=language,
            pages=[OcrPageResult(page_number=1, lines=[line])],
            processing_time_seconds=0.5,
        )

    @staticmethod
    def empty(filename: str = "empty.png", language: str = "en") -> OcrJsonResponse:
        return OcrJsonResponse(
            filename=filename,
            language=language,
            pages=[OcrPageResult(page_number=1, lines=[])],
            processing_time_seconds=0.1,
        )


PNG_MAGIC_BYTES: bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_MAGIC_BYTES: bytes = b"\xff\xd8\xff" + b"\x00" * 16
PDF_MAGIC_BYTES: bytes = b"%PDF-1.7\n" + b"\x00" * 16
