import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.config.config import get_settings
from app.config.logging import setup_logging
from app.db.repository import UploadPlanItemRepository
from app.db.session import build_session_factory
from app.dispatcher.convert_dispatcher import PlanItemConvertDispatcher
from app.extraction.text_extraction_service import TextExtractionService
from app.storage.s3_client import S3Service
from app.workers.convert_worker import ItemConvertWorker

# Настройка логирования
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализирует зависимости приложения и управляет жизненным циклом диспетчера."""
    app_settings = get_settings()
    session_factory = build_session_factory(app_settings)

    repository = UploadPlanItemRepository(app_settings)
    s3_service = S3Service(app_settings)
    extraction_service = TextExtractionService(app_settings)
    worker = ItemConvertWorker(session_factory, repository, s3_service, extraction_service)
    dispatcher = PlanItemConvertDispatcher(app_settings, session_factory, repository, worker)

    app.state.dispatcher = dispatcher
    dispatcher.start()
    try:
        yield
    finally:
        dispatcher.stop()


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
