from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.investigate_code.text_processor import (
    SKIP_FILE_TYPES,
    SKIP_OTHER_SUBTYPES,
    process_raw_text_for_api,
)


@dataclass(frozen=True)
class TextProcessingResult:
    """Результат обработки текста для определения конвертируемости и мета-данных."""

    should_convert: bool
    payload: dict[str, Any]


class TextProcessingService:
    """Сервис обработки уже извлечённого текста (после PDF/DOCX парсинга)."""

    def process(self, filename: str, text: str, method: str) -> TextProcessingResult:
        """Возвращает payload для upload_plan_item.s3_info_type_converted."""
        parsed = process_raw_text_for_api(file_name=filename, raw_text=text)
        doc_type = parsed.get("doc_type") or parsed.get("doc_info", {}).get("type", "other")

        if doc_type in SKIP_FILE_TYPES or doc_type in SKIP_OTHER_SUBTYPES:
            return TextProcessingResult(
                should_convert=False,
                payload={"type": doc_type, "filename": filename},
            )

        return TextProcessingResult(
            should_convert=True,
            payload={
                "info": parsed.get("doc_info", {}),
                "data": parsed.get("essential_data", {}),
                "method": method,
            },
        )
