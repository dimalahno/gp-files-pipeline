from __future__ import annotations

import io

import pytesseract
from PIL import Image

from app.config.config import Settings


class OcrService:
    """Сервис OCR на базе Tesseract для распознавания текста из изображений."""

    def __init__(self, settings: Settings):
        """Считывает конфигурацию языков распознавания из настроек приложения."""
        self.langs = settings.OCR_LANGS

    def extract_from_image_bytes(self, image_bytes: bytes) -> str:
        """Распознает текст из бинарных данных изображения и возвращает строку."""
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image, lang=self.langs)
