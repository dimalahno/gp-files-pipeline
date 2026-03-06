from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config.config import Settings
from app.db.models import UploadPlan, UploadPlanItem, UploadPlanStatus, UploadStatus


class UploadPlanRepository:
    """Репозиторий для работы с агрегированным состоянием плана загрузки."""

    def lock_by_id(self, session: Session, plan_id: int) -> UploadPlan | None:
        """Возвращает план по идентификатору с блокировкой строки для безопасного обновления."""
        stmt = select(UploadPlan).where(UploadPlan.id == plan_id).with_for_update(skip_locked=True)
        return session.scalar(stmt)

    def mark_processing(self, plan: UploadPlan) -> None:
        """Переводит план в статус PROCESSING и сбрасывает ошибку уровня плана."""
        plan.status = UploadPlanStatus.PROCESSING
        plan.last_error = None

    def mark_completed(self, plan: UploadPlan) -> None:
        """Помечает план как полностью успешно завершённый."""
        plan.status = UploadPlanStatus.COMPLETED
        plan.last_error = None

    def mark_completed_with_errors(self, plan: UploadPlan, error_text: str | None = None) -> None:
        """Помечает план как завершённый с ошибками и сохраняет сообщение об ошибке."""
        plan.status = UploadPlanStatus.COMPLETED_WITH_ERRORS
        plan.last_error = error_text

    def mark_failed(self, plan: UploadPlan, error_text: str) -> None:
        """Помечает план как неуспешно завершённый на уровне всего плана."""
        plan.status = UploadPlanStatus.FAILED
        plan.last_error = error_text

    def recalculate_counters(self, plan: UploadPlan, items: list[UploadPlanItem]) -> None:
        """Пересчитывает агрегированные счётчики плана на основании списка элементов."""
        plan.total_items = len(items)
        plan.done_items = sum(1 for item in items if item.status in {UploadStatus.UPLOADED, UploadStatus.CONVERTED, UploadStatus.PROCESSED})
        plan.failed_items = sum(1 for item in items if item.status == UploadStatus.ERROR)


class UploadPlanItemRepository:
    """Репозиторий для выборки и обновления статусов элементов конвертации."""

    def __init__(self, settings: Settings):
        """Сохраняет настройки лимитов и параметров ретраев для операций репозитория."""
        self.settings = settings

    def lock_batch_for_convert(self, session: Session) -> list[UploadPlanItem]:
        """Блокирует пачку готовых к конвертации записей и переводит их в CONVERTING."""
        stmt = (
            select(UploadPlanItem)
            .where(
                and_(
                    UploadPlanItem.status == UploadStatus.UPLOADED,
                    UploadPlanItem.convert_attempt_count < self.settings.MAX_CONVERT_ATTEMPTS,
                    or_(
                        UploadPlanItem.next_retry_at.is_(None),
                        UploadPlanItem.next_retry_at < func.now(),
                    ),
                )
            )
            .order_by(UploadPlanItem.id.asc())
            .limit(self.settings.DISPATCHER_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        items = list(session.scalars(stmt))

        for item in items:
            item.status = UploadStatus.CONVERTING
            item.convert_error = None

        return items

    def mark_converted(
        self,
        item: UploadPlanItem,
        text_s3_path: str,
        text_size: int,
        page_count: int,
        has_ocr: bool,
    ) -> None:
        """Фиксирует успешную конвертацию и сохраняет метаданные извлеченного текста."""
        item.status = UploadStatus.CONVERTED
        item.text_s3_path = text_s3_path
        item.text_size = text_size
        item.page_count = page_count
        item.has_ocr = has_ocr
        item.text_extracted = True
        item.convert_error = None
        item.convert_attempt_count += 1
        item.next_retry_at = None
        item.version += 1

    def mark_convert_error(self, item: UploadPlanItem, error_text: str) -> None:
        """Регистрирует ошибку конвертации и рассчитывает время следующего ретрая."""
        item.convert_attempt_count += 1
        item.convert_error = error_text
        item.status = UploadStatus.ERROR
        item.version += 1

        if item.convert_attempt_count < self.settings.MAX_CONVERT_ATTEMPTS:
            backoff_seconds = 2 ** min(item.convert_attempt_count, 8)
            item.next_retry_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)
        else:
            item.next_retry_at = None
