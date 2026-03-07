from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import UploadPlanItem, UploadStatus
from app.db.repository import UploadPlanItemRepository
from app.db.session import db_session
from app.extraction.text_extraction_service import TextExtractionService
from app.extraction.text_processing_service import TextProcessingService
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
        text_processing_service: TextProcessingService,
    ):
        """Сохраняет зависимости, необходимые для полного цикла обработки элемента."""
        self.session_factory = session_factory
        self.repository = repository
        self.s3_service = s3_service
        self.extraction_service = extraction_service
        self.text_processing_service = text_processing_service

    def process(self, item_id: int) -> None:
        """Обрабатывает один элемент плана конвертации по его идентификатору."""
        try:
            with db_session(self.session_factory) as session:
                item = self._get_item(session, item_id)

                object_key, filename = self._load_source_item_meta(item)

                # Пропуск по типу файла
                doc_info_type, skipped = self.text_processing_service.precheck(filename)
                if skipped is not None and not skipped.converted:
                    logger.info("Skipping item_id=%s file_name=%s", item_id, filename)
                    self.repository.mark_not_converted(item=item, payload=skipped.to_json(),)
                    return

                # Загружаем файл из s3 для конвертации
                s3_object = self.s3_service.download(object_key)

                # Извлекаем текст из документа метод извлечения
                text, has_ocr = self.extraction_service.extract(filename, s3_object.body)
                method_extracted = "OCR" if has_ocr else "text"

                # Обрабатываем текст
                processing_result = self.text_processing_service.process(filename, text, method_extracted)

                if not processing_result.converted:
                    #
                    logger.info("Skipping item_id=%s file_name=%s", item_id, filename)
                    self.repository.mark_not_converted(item=item, payload=processing_result.to_json())
                    return

                # Получим новое имя файл в mark dawn
                md_filename_converted: str = self._change_extension_to_md(filename)
                object_key_converted = f"{item.s3_main_prefix}{item.s3_file_path_converted.value}/{md_filename_converted}"

                # Получаем контент в md в s3
                md_content = self.text_processing_service.generate_markdown(
                    processing_result.payload["info"],
                    processing_result.payload["cleaned"],
                    processing_result.payload["data"],
                    method_extracted, )

                # Загружаем полученный контент в s3
                text_size = self.s3_service.upload_text(object_key_converted, md_content)

                logger.info("Successfully uploaded item_id=%s md_file=%s", item_id, md_filename_converted)

                # Сохраняем информацию о конвертации в базу
                self.repository.mark_converted(item, md_filename_converted, text_size, has_ocr, "")
                logger.info("Successfully converted item_id=%s md_file=%s", item_id, md_filename_converted)
        except Exception as exc:
            # Любая ошибка
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
    def _change_extension_to_md(file_name: str) -> str:
        """'
        Принимает строку с именем файла и возвращает имя с расширением .md
        """
        base, _ = os.path.splitext(file_name)
        return base + ".md"


