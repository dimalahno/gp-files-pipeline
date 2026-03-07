from __future__ import annotations

import logging
import os

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
            with db_session(self.session_factory) as session:
                item = self._get_item(session, item_id)
                # object_key, filename = self._load_source_meta(item_id)

                object_key, filename = self._load_source_item_meta(item)
                s3_object = self.s3_service.download(object_key)

                text, has_ocr = self.extraction_service.extract(filename, s3_object.body)

                filename_converted: str = self._change_extension_to_txt(filename)
                object_key_converted = f"{item.s3_main_prefix}{item.s3_file_path_converted.value}/{filename_converted}"

                logger.info(has_ocr)
                text_size = self.s3_service.upload_text(object_key_converted, text)

                self.repository.mark_converted(item, filename_converted, text_size, has_ocr, "")

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
            object_key = f"{item.s3_main_prefix}{item.s3_file_path_original}/{item.s3_file_name_original}"
            return object_key, item.s3_file_name_originaldef

    def _load_source_item_meta(self, item: UploadPlanItem) -> tuple[str, str]:
        """Читает из сущности путь и имя исходного файла для заданного элемента."""
        if not item.s3_file_path_original or not item.s3_file_name_original:
            raise RuntimeError("Original S3 path or filename is empty")
        object_key = f"{item.s3_main_prefix}{item.s3_file_path_original.value}/{item.s3_file_name_original}"
        return object_key, item.s3_file_name_original

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

    @staticmethod
    def _change_extension_to_txt(file_name: str) -> str:
        """'
        Принимает строку с именем файла и возвращает имя с расширением .txt
        """
        base, _ = os.path.splitext(file_name)
        return base + ".txt"


