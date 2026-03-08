from __future__ import annotations

from pathlib import Path

from app.config.config import Settings
from app.extraction.doc_extractor import DocExtractor
from app.extraction.ocr_service import OcrService
from app.extraction.pdf_extractor import PdfExtractor


class TextExtractionService:
    """Фасад извлечения текста, выбирающий обработчик по расширению файла."""

    def __init__(self, settings: Settings):
        """Инициализирует PDF/DOC-экстракторы и общий OCR-сервис."""
        ocr_service = OcrService(settings)
        self.pdf_extractor = PdfExtractor(settings, ocr_service)
        self.doc_extractor = DocExtractor()

    def extract(self, filename: str, raw_file: bytes) -> tuple[str, bool]:
        """Извлекает текст из файла, возвращая текст, число страниц и признак OCR."""
        ext = Path(filename).suffix.lower()
        if ext == ".pdf":
            # return self.pdf_extractor.extract(raw_file)
            return self.pdf_extractor.extract_fitz(raw_file)
        if ext in {".doc", ".docx"}:
            return self.doc_extractor.extract(raw_file, ext)
        raise RuntimeError(f"Unsupported file extension: {ext}")
