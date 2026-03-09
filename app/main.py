import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.config.config import get_settings
from app.config.logging import setup_logging
from app.db.repository import UploadPlanItemRepository
from app.db.repository import UploadPlanRepository
from app.db.session import build_session_factory
from app.dispatcher.convert_dispatcher import PlanItemConvertDispatcher
from app.dispatcher.processed_dispatcher import PlanItemProcessedDispatcher
from app.dispatcher.workers.convert_worker import ItemConvertWorker
from app.dispatcher.workers.processed_worker import ItemProcessedWorker
from app.extraction.text_extraction_service import TextExtractionService
from app.extraction.text_processing_service import TextProcessingService
from app.storage.s3_client import S3Service

# Настройка логирования
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализирует зависимости приложения и управляет жизненным циклом диспетчера."""
    app_settings = get_settings()
    session_factory = build_session_factory(app_settings)

    repository = UploadPlanItemRepository(app_settings)
    plan_repository = UploadPlanRepository()
    s3_service = S3Service(app_settings)
    extraction_service = TextExtractionService(app_settings)
    text_processing_service = TextProcessingService()
    worker_convert = ItemConvertWorker(
        session_factory,
        repository,
        s3_service,
        extraction_service,
        text_processing_service,
    )
    worker_processed = ItemProcessedWorker(
        session_factory,
        repository,
        processed_service=None,
    )
    dispatcher_convert = PlanItemConvertDispatcher(app_settings, session_factory, repository, worker_convert)
    dispatcher_processed = PlanItemProcessedDispatcher(
        app_settings,
        session_factory,
        plan_repository,
        worker_processed,
    )

    app.state.dispatcher = dispatcher_convert
    app.state.dispatcher_processed = dispatcher_processed
    dispatcher_convert.start()
    dispatcher_processed.start()
    try:
        yield
    finally:
        dispatcher_convert.stop()
        dispatcher_processed.stop()


settings = get_settings()
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.include_router(router, prefix=settings.APP_CONTEXT_PATH)

if __name__ == "__main__":
    settings = get_settings()
    logger.info(f"Swagger: http://{settings.APP_HOST}:{settings.APP_PORT}/docs")
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG_MODE
    )
