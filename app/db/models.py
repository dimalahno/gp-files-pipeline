import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, BigInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый декларативный класс SQLAlchemy для ORM-моделей приложения."""

    pass


class UploadStatus(str, enum.Enum):
    """Перечень статусов обработки файла в конвейере конвертации."""

    CREATED = "CREATED"
    DOWNLOADING = "DOWNLOADING"
    UPLOADED = "UPLOADED"
    CONVERTING = "CONVERTING"
    CONVERTED = "CONVERTED"
    PROCESSED = "PROCESSED"
    ERROR = "ERROR"


class UploadPlanItem(Base):
    """ORM-модель элемента плана загрузки/конвертации файлов."""

    __tablename__ = "upload_plan_item"
    __table_args__ = {"schema": "files_storage"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    case_no: Mapped[str] = mapped_column(String, nullable=False)
    file_identifier: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    request_identifier: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)

    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="upload_plan_item_status", native_enum=False),
        nullable=False,
        default=UploadStatus.CREATED,
    )

    s3_file_path_original: Mapped[str | None] = mapped_column(Text)
    s3_file_name_original: Mapped[str | None] = mapped_column(String)

    convert_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    text_s3_path: Mapped[str | None] = mapped_column(Text)
    text_size: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    has_ocr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    text_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    convert_error: Mapped[str | None] = mapped_column(Text)

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
