from functools import lru_cache

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

model_config = SettingsConfigDict(
    env_file=str(BASE_DIR / ".env"),
    env_file_encoding="utf-8"
)

class Settings(BaseSettings):
    """Настройки FastAPI-сервиса и пути к справочнику санкций."""
    APP_NAME: str = "gp-files-pipeline"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 9001
    APP_CONTEXT_PATH: str = "/files/pipeline"

    DB_URL: str = Field(default="postgresql+psycopg2://postgres:Astana2026@192.168.93.157:5432/gp_cases_db")

    MINIO_ENDPOINT: str = "http://192.168.93.154:9000"
    MINIO_BUCKET: str = "gosobvin"
    MINIO_ACCESS_KEY: str = "admin"
    MINIO_SECRET_KEY: str = "minio12345"
    MINIO_REGION: str = "us-east-1"

    DISPATCHER_INTERVAL_SECONDS: int = 5
    DISPATCHER_BATCH_SIZE: int = 5
    MAX_CONVERT_ATTEMPTS: int = 5
    WORKER_THREADS: int = 4

    TEXT_SUCCESS_THRESHOLD: int = 50
    OCR_LANGS: str = "rus+kaz"

    DEBUG_MODE: bool = True


@lru_cache
def get_settings() -> Settings:
    """Возвращает кешированный экземпляр настроек приложения."""
    return Settings()

settings = get_settings()
