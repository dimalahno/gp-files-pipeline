from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy.orm import Session, sessionmaker

from app.config.config import Settings
from app.db.repository import UploadPlanItemRepository
from app.db.session import db_session
from app.workers.convert_worker import ItemConvertWorker

logger = logging.getLogger(__name__)


class PlanItemConvertDispatcher:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        repository: UploadPlanItemRepository,
        worker: ItemConvertWorker,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.repository = repository
        self.worker = worker

        self.pool = ThreadPoolExecutor(max_workers=settings.WORKER_THREADS, thread_name_prefix="convert")
        self.stop_event = threading.Event()
        self.dispatcher_thread: threading.Thread | None = None

    def start(self) -> None:
        if self.dispatcher_thread and self.dispatcher_thread.is_alive():
            return
        self.dispatcher_thread = threading.Thread(target=self._run_loop, daemon=True, name="convert-dispatcher")
        self.dispatcher_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.dispatcher_thread:
            self.dispatcher_thread.join(timeout=5)
        self.pool.shutdown(wait=False, cancel_futures=True)

    def run_once(self) -> int:
        with db_session(self.session_factory) as session:
            items = self.repository.lock_batch_for_convert(session)
            ids = [item.id for item in items]

        futures: list[Future] = [self.pool.submit(self.worker.process, item_id) for item_id in ids]
        for future in futures:
            future.result()

        if ids:
            logger.info("Dispatched %s items for conversion", len(ids))
        return len(ids)

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Dispatcher loop failed")
            self.stop_event.wait(self.settings.DISPATCHER_INTERVAL_SECONDS)