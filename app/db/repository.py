from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config.config import Settings
from app.db.models import (
    UploadPlan,
    UploadPlanItem,
    UploadPlanItemFilePathType,
    UploadPlanStatus,
    UploadStatus,
)


class UploadPlanRepository:
    """Репозиторий для работы с агрегированным состоянием плана загрузки."""

    def find_converted_plans(self, session: Session) -> list[UploadPlan]:
        """Возвращает все планы со статусом CONVERTED."""
        stmt = (
            select(UploadPlan)
            .where(UploadPlan.status == UploadPlanStatus.CONVERTED)
            .order_by(UploadPlan.id.asc())
        )
        return list(session.scalars(stmt))

    def find_converted_plan_by_id(self, session: Session, plan_id: int) -> list[UploadPlan]:
        """Возвращает все планы со статусом CONVERTED."""
        stmt = (
            select(UploadPlan)
            .where(
                and_(UploadPlan.id == plan_id,
                     UploadPlan.status == UploadPlanStatus.CONVERTED)
            )
            .order_by(UploadPlan.id.asc())
        )
        return list(session.scalars(stmt))

    def mark_completed(self, plan: UploadPlan) -> None:
        """Переводит план в статус COMPLETED и сбрасывает ошибку уровня плана."""
        plan.status = UploadPlanStatus.COMPLETED
        plan.last_error = None


class UploadPlanItemRepository:
    """Репозиторий для выборки и обновления статусов элементов конвертации."""

    def __init__(self, settings: Settings):
        """Сохраняет настройки лимитов и параметров ретраев для операций репозитория."""
        self.settings = settings

    def lock_batch_for_convert(self, session: Session, plan_id: int) -> list[UploadPlanItem]:
        """Блокирует пачку готовых к конвертации записей и переводит их в CONVERTING."""
        stmt = (
            select(UploadPlanItem)
            .where(
                and_(
                    UploadPlanItem.plan_id == plan_id,
                    UploadPlanItem.status == UploadStatus.UPLOADED,
                    UploadPlanItem.convert_attempt_count < self.settings.MAX_CONVERT_ATTEMPTS,
                    or_(
                        UploadPlanItem.convert_next_retry_at.is_(None),
                        UploadPlanItem.convert_next_retry_at < func.now(),
                    ),
                )
            )
            .order_by(UploadPlanItem.id.asc())
            .limit(self.settings.DISPATCHER_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        items = list(session.scalars(stmt))

        # В состоянии конвертации
        for item in items:
            item.status = UploadStatus.CONVERTING
            item.convert_error_message = None

        return items

    def mark_converted(
            self,
            item: UploadPlanItem,
            s3_file_name_converted: str,
            text_size: int,
            has_ocr: bool,
            info_type_converted: dict | list | str | None,
    ) -> None:
        """Фиксирует успешную конвертацию и сохраняет метаданные извлеченного текста."""
        item.status = UploadStatus.CONVERTED
        item.s3_file_name_converted = s3_file_name_converted
        item.converted_text_size = text_size
        item.s3_mime_type_converted = 'text/plain'
        item.has_ocr = has_ocr
        item.is_converted = True
        item.convert_error_message = None
        item.convert_attempt_count += 1
        item.next_retry_at = None
        item.version += 1
        item.s3_info_type_converted = self._serialize_info_type(info_type_converted)


    def created_processed(
        self,
        session: Session,
        source_item: UploadPlanItem,
        processed_file_name: str,
    ) -> UploadPlanItem:
        """Создаёт новый UploadPlanItem со статусом PROCESSED на основе исходного элемента."""
        now = datetime.now()
        processed_item = UploadPlanItem(
            plan_id=source_item.plan_id,
            case_no=source_item.case_no,
            registry_id=source_item.registry_id,
            file_identifier=str(uuid.uuid4()),
            request_identifier=source_item.request_identifier,
            te2_card_id=source_item.te2_card_id,
            jsr_path=source_item.jsr_path,
            order_index=source_item.order_index,
            document_name=source_item.document_name,
            doc_type_id=source_item.doc_type_id,
            doc_type_code=source_item.doc_type_code,
            doc_type_name_ru=source_item.doc_type_name_ru,
            doc_type_name_kk=source_item.doc_type_name_kk,
            doc_spec_id=source_item.doc_spec_id,
            doc_spec_code=source_item.doc_spec_code,
            doc_spec_name_ru=source_item.doc_spec_name_ru,
            doc_spec_name_kk=source_item.doc_spec_name_kk,
            qualification_id=source_item.qualification_id,
            qualification_code=source_item.qualification_code,
            qualification_name_ru=source_item.qualification_name_ru,
            qualification_name_kk=source_item.qualification_name_kk,
            send_date=source_item.send_date,
            s3_main_prefix=source_item.s3_main_prefix,
            s3_file_path_original=source_item.s3_file_path_original,
            s3_file_name_original=source_item.s3_file_name_original,
            s3_file_ext_original=source_item.s3_file_ext_original,
            s3_mime_type_original=source_item.s3_mime_type_original,
            s3_file_path_converted=source_item.s3_file_path_converted,
            s3_file_name_converted=source_item.s3_file_name_converted,
            s3_file_path_processed=UploadPlanItemFilePathType.PROCESSED,
            s3_file_name_processed=processed_file_name,
            status=UploadStatus.PROCESSED,
            status_changed_at=now,
            error_message=None,
            created_at=now,
            updated_at=now,
            jr_file_exist=source_item.jr_file_exist,
            jr_file_size=source_item.jr_file_size,
            jr_mime_type=source_item.jr_mime_type,
            version=0,
            attempt_count=0,
            next_retry_at=None,
            is_uploaded=True,
            is_converted=True,
            is_processed=True,
            convert_attempt_count=source_item.convert_attempt_count,
            convert_next_retry_at=None,
            convert_error_message=None,
            converted_text_size=source_item.converted_text_size,
            has_ocr=source_item.has_ocr,
            s3_mime_type_converted=source_item.s3_mime_type_converted,
            s3_info_type_converted=source_item.s3_info_type_converted,
        )
        session.add(processed_item)
        return processed_item

    def mark_not_converted(self, item: UploadPlanItem, payload: str) -> None:
        """Фиксирует что файл не подлежит конвертации устанавливаем статус."""
        item.status = UploadStatus.NOT_CONVERTED
        item.has_ocr = False
        item.is_converted = True
        item.convert_error_message = None
        item.convert_attempt_count += 1
        item.next_retry_at = None
        item.version += 1
        item.s3_info_type_converted = payload

    @staticmethod
    def _serialize_info_type(info_type: dict | list | str | None) -> str | None:
        """Преобразует мета-информацию о типе контента в строку для сохранения в БД."""
        if info_type is None:
            return None
        if isinstance(info_type, str):
            return info_type
        return json.dumps(info_type, ensure_ascii=False)

    def mark_convert_error(self, item: UploadPlanItem, error_text: str) -> None:
        """Регистрирует ошибку конвертации и рассчитывает время следующего ретрая."""
        item.convert_attempt_count += 1
        item.convert_error_message = error_text
        item.status = UploadStatus.CONVERTED_ERROR
        item.is_converted = True
        item.version += 1

        if item.convert_attempt_count < self.settings.MAX_CONVERT_ATTEMPTS:
            backoff_seconds = 2 ** min(item.convert_attempt_count, 8)
            item.next_retry_at = datetime.now() + timedelta(seconds=backoff_seconds)
        else:
            item.next_retry_at = None

    def find_converted_items(self, session: Session, plan_id: int) -> list[UploadPlanItem]:
        """Возвращает элементы плана со статусами CONVERTED и NOT_CONVERTED."""
        stmt = (
            select(UploadPlanItem)
            .where(
                UploadPlanItem.plan_id == plan_id,
                UploadPlanItem.status.in_(
                    [
                        UploadStatus.CONVERTED,
                        UploadStatus.NOT_CONVERTED,
                    ]
                ),
            )
            .order_by(UploadPlanItem.id.asc())
        )
        return list(session.scalars(stmt))
