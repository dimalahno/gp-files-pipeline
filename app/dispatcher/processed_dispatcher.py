from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import Session, sessionmaker

from app.config.config import Settings
from app.db.repository import UploadPlanRepository
from app.db.session import db_session
from app.dispatcher.workers.processed_worker import ItemProcessedWorker

logger = logging.getLogger(__name__)


class PlanItemProcessedDispatcher:
    """Диспетчер финальной обработки планов: берет планы CONVERTED и запускает worker строго по одному."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        plan_repository: UploadPlanRepository,
        worker: ItemProcessedWorker,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.plan_repository = plan_repository
        self.worker = worker

        self.stop_event = threading.Event()
        self.dispatcher_thread: threading.Thread | None = None

    def start(self) -> None:
        """Запускает фоновый цикл диспетчеризации."""
        if self.dispatcher_thread and self.dispatcher_thread.is_alive():
            return

        self.dispatcher_thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="processed-dispatcher",
        )
        self.dispatcher_thread.start()

    def stop(self) -> None:
        """Останавливает диспетчер."""
        self.stop_event.set()
        if self.dispatcher_thread:
            self.dispatcher_thread.join(timeout=5)

    def run_once(self) -> int:
        """
        Выполняет одну итерацию:
        1. Находит все планы со статусом CONVERTED
        2. Обрабатывает каждый план строго последовательно
        """
        with db_session(self.session_factory) as session:
            # plans = self.plan_repository.find_converted_plans(session)
            plans = self.plan_repository.find_converted_plan_by_id(session, 21)
            plan_ids = [plan.id for plan in plans]

        processed_count = 0

        for plan_id in plan_ids:
            try:
                self.worker.process_processing(plan_id)
                processed_count += 1
            except Exception:
                logger.exception("Failed to process plan_id=%s", plan_id)

        if processed_count:
            logger.info("Processed %s converted plans", processed_count)

        return processed_count

    def _run_loop(self) -> None:
        """Бесконечный цикл диспетчера с заданным интервалом."""
        while not self.stop_event.is_set():
            try:
                self.run_once()
                logger.info("Processed processed_dispatcher loop")
            except Exception:
                logger.exception("Processed dispatcher loop failed")

            self.stop_event.wait(self.settings.DISPATCHER_INTERVAL_SECONDS)