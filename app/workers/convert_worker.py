from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import UploadPlanItem, UploadStatus
from app.db.repository import UploadPlanItemRepository
from app.db.session import db_session
from app.extraction.text_extraction_service import TextExtractionService
from app.storage.s3_client import S3Service

logger = logging.getLogger(__name__)


class ItemConvertWorker:
    """Воркер конвертации: скачивает файл, извлекает текст и обновляет статус в БД."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        repository: UploadPlanItemRepository,
        s3_service: S3Service,
        extraction_service: TextExtractionService,
    ):
        """Сохраняет зависимости, необходимые для полного цикла обработки элемента."""
        self.session_factory = session_factory
        self.repository = repository
        self.s3_service = s3_service
        self.extraction_service = extraction_service

    def process(self, item_id: int) -> None:
        """Обрабатывает один элемент плана конвертации по его идентификатору."""
        try:
            object_key, filename = self._load_source_meta(item_id)
            s3_object = self.s3_service.download(object_key)
            text, page_count, has_ocr = self.extraction_service.extract(filename, s3_object.body)
            text_key = f"converted/{self._load_plan_id(item_id)}/{item_id}.txt"
            text_size = self.s3_service.upload_text(text_key, text)

            with db_session(self.session_factory) as session:
                item = self._get_item(session, item_id)
                self.repository.mark_converted(item, text_key, text_size, page_count, has_ocr)

            logger.info("Successfully converted item_id=%s", item_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to convert item_id=%s", item_id)
            with db_session(self.session_factory) as session:
                item = self._get_item(session, item_id)
                # Сохраняем только короткий текст ошибки, чтобы не переполнять поле в БД трассировкой.
                self.repository.mark_convert_error(item, str(exc)[:4000])

    def _load_source_meta(self, item_id: int) -> tuple[str, str]:
        """Читает из БД путь и имя исходного файла для заданного элемента."""
        with db_session(self.session_factory) as session:
            item = self._get_item(session, item_id)
            if not item.s3_file_path_original or not item.s3_file_name_original:
                raise RuntimeError("Original S3 path or filename is empty")
            return item.s3_file_path_original, item.s3_file_name_original

    def _load_plan_id(self, item_id: int) -> int:
        """Возвращает идентификатор плана, к которому относится элемент."""
        with db_session(self.session_factory) as session:
            item = self._get_item(session, item_id)
            return item.plan_id

    @staticmethod
    def _get_item(session: Session, item_id: int) -> UploadPlanItem:
        """Извлекает элемент из БД и валидирует его допустимый статус обработки."""
        stmt = select(UploadPlanItem).where(UploadPlanItem.id == item_id)
        item = session.scalar(stmt)
        if item is None:
            raise RuntimeError(f"UploadPlanItem not found for id={item_id}")
        if item.status not in {UploadStatus.CONVERTING, UploadStatus.ERROR, UploadStatus.UPLOADED}:
            raise RuntimeError(f"UploadPlanItem id={item_id} has invalid status={item.status}")
        return item
