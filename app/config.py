from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    app_name: str = "gp-files-pipeline"
    app_host: str = "0.0.0.0"
    app_port: int = 9001
    app_context_path: str = "/files/pipeline"

    db_url: str = Field(
        default="postgresql+psycopg2://postgres:Astana2026@192.168.93.157:5432/gp_cases_db"
    )

    minio_endpoint: str = "http://192.168.93.154:9000"
    minio_bucket: str = "gosobvin"
    minio_access_key: str = "admin"
    minio_secret_key: str = "minio12345"
    minio_region: str = "us-east-1"

    dispatcher_interval_seconds: int = 5
    dispatcher_batch_size: int = 5
    max_convert_attempts: int = 5
    worker_threads: int = 2

    text_success_threshold: int = 50
    ocr_langs: str = "rus+kaz+eng"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()