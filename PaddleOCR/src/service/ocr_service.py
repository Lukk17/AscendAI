import os
import tempfile
import time
from paddleocr import PaddleOCR
from src.config.config import settings
from src.config.logging_config import get_logger
from src.model.ocr_models import (
    OcrTextLine,
    OcrPageResult,
    OcrJsonResponse,
)
from typing import Union

logger = get_logger(__name__)


class OcrService:
    def __init__(self) -> None:
        self._engines: dict[str, PaddleOCR] = {}

    def process_file(
            self,
            file_bytes: bytes,
            filename: str,
            language: str,
    ) -> OcrJsonResponse:
        start_time: float = time.monotonic()
        engine: PaddleOCR = self._get_engine(language)

        file_ext = os.path.splitext(filename)[1]
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as temp_file:
            temp_file.write(file_bytes)
            temp_file_path: str = temp_file.name

        try:
            ocr_result = engine.predict(temp_file_path)
            text_lines: list[OcrTextLine] = self._extract_text_lines(ocr_result)
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
        elapsed: float = round(time.monotonic() - start_time, 3)

        return self._build_json_response(
            filename=filename,
            language=language,
            lines=text_lines,
            elapsed=elapsed,
        )

    def warm_up_engine(self, language: str) -> None:
        logger.info(f"Warming up OCR engine for language: {language}")
        self._get_engine(language)

    def _get_engine(self, language: str) -> PaddleOCR:
        if language in self._engines:
            return self._engines[language]
        engine = PaddleOCR(
            lang=language,
            enable_mkldnn=False,
        )
        self._engines[language] = engine
        return engine

    def _extract_text_lines(self, ocr_result: list | None) -> list[OcrTextLine]:
        if not ocr_result:
            return []

        text_lines: list[OcrTextLine] = []
        for page_data in ocr_result:
            if not page_data or not isinstance(page_data, dict):
                continue

            rec_texts = page_data.get("rec_texts", [])
            rec_scores = page_data.get("rec_scores", [])
            dt_polys = page_data.get("dt_polys", [])

            for _text, score, box in zip(rec_texts, rec_scores, dt_polys):
                text_lines.append(
                    OcrTextLine(
                        text=_text,
                        confidence=score,
                        bounding_box=box,
                    )
                )

        return text_lines

    def _convert_polygon(self, polygon) -> list[list[float]]:
        try:
            return [[float(point[0]), float(point[1])] for point in polygon]
        except (TypeError, IndexError, ValueError):
            return []

    def _build_json_response(
            self,
            filename: str,
            language: str,
            lines: list[OcrTextLine],
            elapsed: float,
    ) -> OcrJsonResponse:
        page_result = OcrPageResult(page_number=1, lines=lines)
        return OcrJsonResponse(
            filename=filename,
            language=language,
            pages=[page_result],
            processing_time_seconds=elapsed,
        )


ocr_service = OcrService()
