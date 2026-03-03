import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.db.repository import UploadPlanItemRepository
from app.db.session import build_session_factory
from app.dispatcher.convert_dispatcher import PlanItemConvertDispatcher
from app.extraction.text_extraction_service import TextExtractionService
from app.storage.s3_client import S3Service
from app.workers.convert_worker import ItemConvertWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(router, prefix=settings.app_context_path)