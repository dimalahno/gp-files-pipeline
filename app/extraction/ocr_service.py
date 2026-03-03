from __future__ import annotations

import io

import pytesseract
from PIL import Image

from app.config.config import Settings


class OcrService:
    def __init__(self, settings: Settings):
        self.langs = settings.OCR_LANGS

    def extract_from_image_bytes(self, image_bytes: bytes) -> str:
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image, lang=self.langs)