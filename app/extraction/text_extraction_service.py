from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.extraction.doc_extractor import DocExtractor
from app.extraction.ocr_service import OcrService
from app.extraction.pdf_extractor import PdfExtractor


class TextExtractionService:
    def __init__(self, settings: Settings):
        ocr_service = OcrService(settings)
        self.pdf_extractor = PdfExtractor(settings, ocr_service)
        self.doc_extractor = DocExtractor()

    def extract(self, filename: str, raw_file: bytes) -> tuple[str, int, bool]:
        ext = Path(filename).suffix.lower()
        if ext == ".pdf":
            return self.pdf_extractor.extract(raw_file)
        if ext in {".doc", ".docx"}:
            return self.doc_extractor.extract(raw_file, ext)
        raise RuntimeError(f"Unsupported file extension: {ext}")