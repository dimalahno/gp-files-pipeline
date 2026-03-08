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

        # Если количество извлечённых символов больше TEXT_SUCCESS_THRESHOLD = 50 не применяем osr
        if len(text) >= self.settings.TEXT_SUCCESS_THRESHOLD:
            return text, False

        doc = fitz.open(stream=raw_file, filetype="pdf")
        ocr_text_parts: list[str] = []
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            ocr_text_parts.append(self.ocr_service.extract_from_image_bytes(pix.tobytes("png")))

        ocr_text = "\n".join(ocr_text_parts).strip()
        return ocr_text, True

    def extract_fitz(self, raw_file: bytes) -> tuple[str, bool]:
        """
        Сначала извлекает текст через fitz.get_text().
        Если длина текста меньше TEXT_SUCCESS_THRESHOLD, применяет OCR.
        Возвращает: (text, has_ocr)
        """
        doc = fitz.open(stream=raw_file, filetype="pdf")
        try:
            text_parts: list[str] = []

            for page in doc:
                page_text = page.get_text("text") or ""
                page_text = page_text.strip()
                if page_text:
                    text_parts.append(page_text)

            text = "\n".join(text_parts).strip()

            if len(text) >= self.settings.TEXT_SUCCESS_THRESHOLD:
                return text, False

            ocr_text_parts: list[str] = []

            for page in doc:
                mat = fitz.Matrix(2, 2)
                pix = page.get_pixmap(matrix=mat)
                page_text = self.ocr_service.extract_from_image_bytes(pix.tobytes("png")) or ""
                page_text = page_text.strip()
                if page_text:
                    ocr_text_parts.append(page_text)

            ocr_text = "\n".join(ocr_text_parts).strip()
            return ocr_text, True
        finally:
            doc.close()

    # def extract_via_fitz(self, raw_file: bytes) -> tuple[str, bool]:
    #     """
    #     Извлечение текста только через fitz.get_text().
    #     OCR не используется.
    #     """
    #     doc = fitz.open(stream=raw_file, filetype="pdf")
    #     try:
    #         text_parts: list[str] = []
    #
    #         for page in doc:
    #             page_text = page.get_text("text") or ""
    #             page_text = page_text.strip()
    #             if page_text:
    #                 text_parts.append(page_text)
    #
    #         text = "\n".join(text_parts).strip()
    #         return text, False
    #     finally:
    #         doc.close()
    #
    # def extract_via_ocr(self, raw_file: bytes) -> tuple[str, bool]:
    #     """
    #     Извлечение текста только через OCR.
    #     """
    #     doc = fitz.open(stream=raw_file, filetype="pdf")
    #     try:
    #         ocr_text_parts: list[str] = []
    #
    #         for page in doc:
    #             mat = fitz.Matrix(2, 2)
    #             pix = page.get_pixmap(matrix=mat)
    #             page_text = self.ocr_service.extract_from_image_bytes(pix.tobytes("png")) or ""
    #             page_text = page_text.strip()
    #             if page_text:
    #                 ocr_text_parts.append(page_text)
    #
    #         ocr_text = "\n".join(ocr_text_parts).strip()
    #         return ocr_text, True
    #     finally:
    #         doc.close()