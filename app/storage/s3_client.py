from __future__ import annotations

import io
from dataclasses import dataclass

import boto3

from app.config.config import Settings


@dataclass
class S3Object:
    """Контейнер с телом объекта и его MIME-типом, загруженного из S3."""

    body: bytes
    content_type: str | None


class S3Service:
    """Сервис для чтения исходных файлов и записи результатов в S3-совместимое хранилище."""

    def __init__(self, settings: Settings):
        """Создает S3-клиент на основе настроек подключения и бакета."""
        self.bucket = settings.MINIO_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=settings.MINIO_REGION,
        )

    def download(self, key: str) -> S3Object:
        """Скачивает объект по ключу и возвращает его содержимое с метаданными."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"].read()
        return S3Object(body=body, content_type=response.get("ContentType"))

    def upload_text(self, key: str, text: str) -> int:
        """Загружает текстовый результат в UTF-8 и возвращает размер в байтах."""
        payload = text.encode("utf-8")
        self.client.upload_fileobj(
            io.BytesIO(payload),
            Bucket=self.bucket,
            Key=key,
            ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
        )
        return len(payload)
