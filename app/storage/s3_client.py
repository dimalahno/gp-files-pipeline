from __future__ import annotations

import io
from dataclasses import dataclass

import boto3

from app.config import Settings


@dataclass
class S3Object:
    body: bytes
    content_type: str | None


class S3Service:
    def __init__(self, settings: Settings):
        self.bucket = settings.minio_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name=settings.minio_region,
        )

    def download(self, key: str) -> S3Object:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"].read()
        return S3Object(body=body, content_type=response.get("ContentType"))

    def upload_text(self, key: str, text: str) -> int:
        payload = text.encode("utf-8")
        self.client.upload_fileobj(
            io.BytesIO(payload),
            Bucket=self.bucket,
            Key=key,
            ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
        )
        return len(payload)