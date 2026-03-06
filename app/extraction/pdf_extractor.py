from __future__ import annotations

import io

import pymupdf as fitz
from pypdf import PdfReader

from app.config.config import Settings
from app.extraction.ocr_service import OcrService


class PdfExtractor:
    """Извлекает текст из PDF сначала напрямую, при нехватке текста — через OCR."""

    def __init__(self, settings: Settings, ocr_service: OcrService):
        """Сохраняет настройки порога качества текста и OCR-сервис."""
        self.settings = settings
        self.ocr_service = ocr_service

    def extract(self, raw_file: bytes) -> tuple[str, bool]:
        """Возвращает текст PDF, количество страниц и признак использования OCR."""
        reader = PdfReader(io.BytesIO(raw_file))
        text = "\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()

        if len(text) >= self.settings.TEXT_SUCCESS_THRESHOLD:
            return text, False

        doc = fitz.open(stream=raw_file, filetype="pdf")
        ocr_text_parts: list[str] = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            ocr_text_parts.append(self.ocr_service.extract_from_image_bytes(pix.tobytes("png")))

        ocr_text = "\n".join(ocr_text_parts).strip()
        return ocr_text, True
