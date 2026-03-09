from __future__ import annotations

import json
import logging
import uuid
from typing import Dict

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import UploadPlan, UploadPlanStatus, UploadStatus
from app.db.repository import UploadPlanItemRepository
from app.db.session import db_session
from app.extraction.case_summary_service import generate_case_summary
from app.extraction.index_document_service import generate_index_document
from app.storage.s3_client import S3Service

logger = logging.getLogger(__name__)


class ItemProcessedWorker:
    """
    Воркер финальной обработки плана.
    Для одного plan_id загружает все UploadPlanItem со статусами CONVERTED / NOT_CONVERTED
    и запускает финальный пост-процессинг.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        item_repository: UploadPlanItemRepository,
        s3_service: S3Service,
    ):
        self.session_factory = session_factory
        self.item_repository = item_repository
        self.s3_service = s3_service

    def process_processing(self, plan_id: int) -> None:
        """
        Обрабатывает один план:
        1. Загружает сам план
        2. Переводит его в PROCESSING
        3. Получает все UploadPlanItem для плана
        4. Передает их в финальный сервис
        5. При успехе переводит план в COMPLETED
        6. При ошибке переводит план в FAILED
        """
        try:
            with db_session(self.session_factory) as session:
                plan = self._get_plan(session, plan_id)
                items = self.item_repository.find_converted_items(session, plan_id)

                if not items:
                    logger.error("No converted items found for plan_id=%s", plan_id)
                    return
                all_docs = []
                skipped_docs = []

                for item in items:
                    if item.status == UploadStatus.CONVERTED:
                        all_docs.append(self._str_to_dict(item.s3_info_type_converted))
                    if item.status == UploadStatus.NOT_CONVERTED:
                        skipped_docs.append(self._str_to_dict(item.s3_info_type_converted))

                index_file: str = generate_index_document(all_docs, skipped_docs)
                summary_file: str = generate_case_summary(all_docs)

                # Новое имя markdown файла
                index_uid = self._generate_uuid()
                summary_uid = self._generate_uuid()
                index_md_filename = f"index_{plan.case_no}_{index_uid}.md"
                summary_md_filename = f"summary_{plan.case_no}_{summary_uid}.md"

                object_key_processed_index = (
                    f"{item.s3_main_prefix}"
                    f"{item.s3_file_path_processed.value}/"
                    f"{index_md_filename}"
                )

                object_key_processed_summary = (
                    f"{item.s3_main_prefix}"
                    f"{item.s3_file_path_processed.value}/"
                    f"{summary_md_filename}"
                )

                # Загрузка markdown в s3
                self.s3_service.upload_text(object_key_processed_index, index_file)
                self.s3_service.upload_text(object_key_processed_summary, summary_file)

                # Сохраняем информацию об файлах индексе и справке
                self.item_repository.created_processed(session, items[0], index_uid, index_md_filename)
                self.item_repository.created_processed(session, items[0], summary_uid, summary_md_filename)

                self._mark_completed(plan)
                logger.info("Successfully processed plan_id=%s", plan_id)

        except Exception as exc:
            logger.exception("Failed to process plan_id=%s", plan_id)
            raise

    @staticmethod
    def _get_plan(session: Session, plan_id: int) -> UploadPlan:
        """Возвращает план по id и валидирует допустимый статус."""
        stmt = select(UploadPlan).where(UploadPlan.id == plan_id)
        plan = session.scalar(stmt)

        if plan is None:
            raise RuntimeError(f"UploadPlan not found for id={plan_id}")

        if plan.status not in {UploadPlanStatus.CONVERTED, UploadPlanStatus.PROCESSING}:
            raise RuntimeError(f"UploadPlan id={plan_id} has invalid status={plan.status}")

        return plan

    @staticmethod
    def _mark_completed(plan: UploadPlan) -> None:
        """Переводит план в статус COMPLETED."""
        plan.status = UploadPlanStatus.COMPLETED
        plan.last_error = None

    @staticmethod
    def _str_to_dict(data: str) -> Dict[str, str]:
        return json.loads(data)

    @staticmethod
    def _generate_uuid() -> str:
        return str(uuid.uuid4())
