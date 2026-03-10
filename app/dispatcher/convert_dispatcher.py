from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy.orm import Session, sessionmaker

from app.config.config import Settings
from app.db.repository import UploadPlanItemRepository
from app.db.session import db_session
from app.dispatcher.workers.convert_worker import ItemConvertWorker

logger = logging.getLogger(__name__)


class PlanItemConvertDispatcher:
    """Планировщик, который выбирает задачи из БД и распределяет их по воркерам."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        repository: UploadPlanItemRepository,
        worker: ItemConvertWorker,
    ):
        """Инициализирует пул потоков и примитивы управления циклом диспетчера."""
        self.settings = settings
        self.session_factory = session_factory
        self.repository = repository
        self.worker = worker

        self.pool = ThreadPoolExecutor(max_workers=settings.WORKER_THREADS, thread_name_prefix="convert")
        self.stop_event = threading.Event()
        self.dispatcher_thread: threading.Thread | None = None

    def start(self) -> None:
        """Запускает фоновый поток циклической диспетчеризации задач."""
        if self.dispatcher_thread and self.dispatcher_thread.is_alive():
            return
        self.dispatcher_thread = threading.Thread(target=self._run_loop, daemon=True, name="convert-dispatcher")
        self.dispatcher_thread.start()

    def stop(self) -> None:
        """Останавливает цикл диспетчера и завершает пул рабочих потоков."""
        self.stop_event.set()
        if self.dispatcher_thread:
            self.dispatcher_thread.join(timeout=5)
        self.pool.shutdown(wait=False, cancel_futures=True)

    def run_once(self) -> int:
        """Выполняет одну итерацию: резервирует задачи и обрабатывает их параллельно."""
        with db_session(self.session_factory) as session:
            # TODO временно для отладки, в проде отключим
            # plan_id: int = 22
            # items = self.repository.lock_batch_for_convert_by_plan_id(session, plan_id)

            items = self.repository.lock_batch_for_convert(session)
            ids = [item.id for item in items]

        futures: list[Future] = [self.pool.submit(self.worker.process_convert, item_id) for item_id in ids]
        for future in futures:
            future.result()

        if ids:
            logger.info("Dispatched %s items for conversion", len(ids))
        return len(ids)

    def _run_loop(self) -> None:
        """Непрерывно запускает итерации диспетчеризации с заданным интервалом."""
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Dispatcher loop failed")
            self.stop_event.wait(self.settings.DISPATCHER_INTERVAL_SECONDS)
