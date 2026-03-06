import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый декларативный класс SQLAlchemy для ORM-моделей приложения."""

    pass


class UploadPlanItemFilePathType(str, enum.Enum):
    """Тип пути файла: оригинал, сконвертированный или обработанный."""

    ORIGINAL = "ORIGINAL"
    CONVERTED = "CONVERTED"
    PROCESSED = "PROCESSED"


class UploadStatus(str, enum.Enum):
    """Операционный статус обработки файла в конвейере."""

    CREATED = "CREATED"
    DOWNLOADING = "DOWNLOADING"
    UPLOADED = "UPLOADED"
    CONVERTED = "CONVERTED"
    CONVERTING = "CONVERTING"
    NOT_CONVERTED = "NOT_CONVERTED"
    CONVERTED_ERROR = "CONVERTED_ERROR"
    PROCESSED = "PROCESSED"
    PROCESSING = "PROCESSING"
    NOT_PROCESSED = "NOT_PROCESSED"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    ERROR = "ERROR"
    ERROR_UUID = "ERROR_UUID"
    ERROR_FILE_NOT_FOUND = "ERROR_FILE_NOT_FOUND"
    ERROR_FILE_NOT_EXIST = "ERROR_FILE_NOT_EXIST"
    ERROR_FILE_NOT_SIZE = "ERROR_FILE_NOT_SIZE"
    ERROR_JSR_PATH_EMPTY = "ERROR_JSR_PATH_EMPTY"


class UploadPlanStatus(str, enum.Enum):
    """Статусы обработки плана загрузки."""

    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    UPLOADED = "UPLOADED"
    CONVERTED = "CONVERTED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class UploadPlan(Base):
    """План загрузки файлов для конкретного дела и версии синхронизации."""

    __tablename__ = "upload_plan"
    __table_args__ = (
        UniqueConstraint("case_no", "version", name="upload_plan_case_version_uq"),
        {"schema": "files_storage"},
    )

    #: PK записи плана.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: Идентификатор надзорного производства.
    registry_id: Mapped[int | None] = mapped_column(BigInteger)
    #: Номер дела ЕРДР, по которому сформирован план.
    case_no: Mapped[str] = mapped_column(String, nullable=False)
    #: Статус обработки плана.
    status: Mapped[UploadPlanStatus] = mapped_column(
        Enum(UploadPlanStatus, name="upload_plan_status", native_enum=False),
        nullable=False,
    )
    #: JSON-план в виде текста (источник истины для воспроизведения).
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    #: Хэш плана (например sha256) для идемпотентности.
    plan_hash: Mapped[str | None] = mapped_column(String)
    #: Версия плана в рамках одного case_no.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Количество элементов (файлов) в плане.
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Количество элементов, завершённых успешно.
    done_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Количество элементов, завершённых с финальной ошибкой.
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Дата/время создания записи плана.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    #: Дата/время последнего обновления записи плана.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    #: Ошибка уровня плана (не по отдельным файлам).
    last_error: Mapped[str | None] = mapped_column(Text)


class UploadPlanItem(Base):
    """Элемент плана загрузки файла с техническими и бизнес-метаданными."""

    __tablename__ = "upload_plan_item"
    __table_args__ = (
        UniqueConstraint("plan_id", "file_identifier", name="upload_plan_item_unique"),
        {"schema": "files_storage"},
    )

    #: PK записи элемента плана.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: FK на files_storage.upload_plan — версия плана загрузки.
    plan_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Номер дела (ЕРДР).
    case_no: Mapped[str] = mapped_column(String, nullable=False)
    #: Идентификатор надзорного производства.
    registry_id: Mapped[int | None] = mapped_column(BigInteger)
    #: UUID файла из источника (уникален в рамках плана).
    file_identifier: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    #: UUID запроса/пакета передачи из источника.
    request_identifier: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    #: Идентификатор карточки TE2.
    te2_card_id: Mapped[str] = mapped_column(String, nullable=False)
    #: Путь к файлу в Jackrabbit (JCR).
    jsr_path: Mapped[str | None] = mapped_column(String)
    #: Порядковый номер документа в источнике.
    order_index: Mapped[int | None] = mapped_column(Integer)
    #: Оригинальное имя документа из источника.
    document_name: Mapped[str | None] = mapped_column(String)
    #: ID типа документа.
    doc_type_id: Mapped[int | None] = mapped_column(BigInteger)
    #: Код типа документа.
    doc_type_code: Mapped[str | None] = mapped_column(String)
    #: Наименование типа документа (RU).
    doc_type_name_ru: Mapped[str | None] = mapped_column(String)
    #: Наименование типа документа (KK).
    doc_type_name_kk: Mapped[str | None] = mapped_column(String)
    #: ID спецификации (вида) документа.
    doc_spec_id: Mapped[int | None] = mapped_column(BigInteger)
    #: Код спецификации (вида) документа.
    doc_spec_code: Mapped[str | None] = mapped_column(String)
    #: Наименование спецификации документа (RU).
    doc_spec_name_ru: Mapped[str | None] = mapped_column(String)
    #: Наименование спецификации документа (KK).
    doc_spec_name_kk: Mapped[str | None] = mapped_column(String)
    #: ID квалификации.
    qualification_id: Mapped[str | None] = mapped_column(String)
    #: Код квалификации.
    qualification_code: Mapped[str | None] = mapped_column(String)
    #: Наименование квалификации (RU).
    qualification_name_ru: Mapped[str | None] = mapped_column(String)
    #: Наименование квалификации (KK).
    qualification_name_kk: Mapped[str | None] = mapped_column(String)
    #: Дата отправки документа из источника.
    send_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    #: Основной префикс для файлов в S3.
    s3_main_prefix: Mapped[str | None] = mapped_column(String)
    #: Путь/тип оригинального файла в S3/MinIO.
    s3_file_path_original: Mapped[UploadPlanItemFilePathType | None] = mapped_column(
        Enum(UploadPlanItemFilePathType, name="upload_plan_item_file_path_type", native_enum=False)
    )
    #: Имя оригинального файла в S3/MinIO.
    s3_file_name_original: Mapped[str | None] = mapped_column(String)
    #: Расширение оригинального файла в S3/MinIO.
    s3_file_ext_original: Mapped[str | None] = mapped_column(String(10))
    #: MIME-тип оригинального файла в S3/MinIO.
    s3_mime_type_original: Mapped[str | None] = mapped_column(String)
    #: Путь/тип сконвертированного файла в S3/MinIO.
    s3_file_path_converted: Mapped[UploadPlanItemFilePathType | None] = mapped_column(
        Enum(UploadPlanItemFilePathType, name="upload_plan_item_file_path_type", native_enum=False)
    )
    #: Имя сконвертированного файла в S3/MinIO.
    s3_file_name_converted: Mapped[str | None] = mapped_column(String)
    #: Путь/тип обработанного файла в S3/MinIO.
    s3_file_path_processed: Mapped[UploadPlanItemFilePathType | None] = mapped_column(
        Enum(UploadPlanItemFilePathType, name="upload_plan_item_file_path_type", native_enum=False)
    )
    #: Имя обработанного файла в S3/MinIO.
    s3_file_name_processed: Mapped[str | None] = mapped_column(String)
    #: Операционный статус обработки (главный state machine).
    status: Mapped[UploadStatus] = mapped_column(
        Enum(UploadStatus, name="upload_plan_item_status", native_enum=False),
        nullable=False,
        default=UploadStatus.CREATED,
    )
    #: Дата последнего изменения статуса.
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=False)
    #: Описание последней ошибки обработки файла.
    error_message: Mapped[str | None] = mapped_column(String)
    #: Дата создания записи.
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=False)
    #: Дата последнего обновления записи.
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=False)
    #: Флаг: доступен ли файл для загрузки.
    jr_file_exist: Mapped[bool | None] = mapped_column(Boolean)
    #: Размер файла в байтах.
    jr_file_size: Mapped[int | None] = mapped_column(BigInteger)
    #: MIME-тип файла в Jackrabbit.
    jr_mime_type: Mapped[str | None] = mapped_column(String)
    #: Версия для оптимистичной блокировки.
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: Количество попыток обработки (скачивание/загрузка в S3).
    attempt_count: Mapped[int | None] = mapped_column(Integer, nullable=False, default=0)
    #: Момент, когда запись можно снова взять в обработку после ошибки.
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    #: Флаг, что файл загружен (status = UPLOADED).
    is_uploaded: Mapped[bool | None] = mapped_column(Boolean, nullable=False, default=False)
    #: Флаг, что файл сконвертирован в txt (status = CONVERTED).
    is_converted: Mapped[bool | None] = mapped_column(Boolean, nullable=False, default=False)
    #: Флаг, что файл обработан (status = PROCESSED).
    is_processed: Mapped[bool | None] = mapped_column(Boolean, nullable=False, default=False)
    #: Количество попыток конвертации.
    convert_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Время следующей попытки конвертации.
    convert_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    #: Сообщение об ошибке, возникшей при конвертации.
    convert_error_message: Mapped[str | None] = mapped_column(String)
    #: Размер сконвертированного текста.
    converted_text_size: Mapped[int | None] = mapped_column(BigInteger)
    #: Признак, использовался ли OCR.
    has_ocr: Mapped[bool] = mapped_column(Boolean)
    #: MIME-тип сконвертированного файла, сохранённого в S3
    s3_mime_type_converted: Mapped[str | None] = mapped_column(String)
