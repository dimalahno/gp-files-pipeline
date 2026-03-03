datasource:
  jdbc-url: jdbc:postgresql://192.168.93.157:5432/gp_cases_db
  username: postgres
  password: Astana2026


minio:
  endpoint: http://192.168.93.154:9000
  bucket: gosobvin
  access-key: admin
  secret-key: minio12345
  region: us-east-1

models:
/**
 * Элементы плана загрузки файлов.
 * Хранит строки из sc.get_case_documents и операционные статусы обработки.
 */
@Entity
@Table(
        name = "upload_plan_item",
        schema = "files_storage",
        uniqueConstraints = {
                @UniqueConstraint(
                        name = "upload_plan_item_unique",
                        columnNames = {"plan_id", "file_identifier"}
                )
        }
)
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UploadPlanItem {

    /**
     * PK записи элемента плана
     */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * FK на files_storage.upload_plan. Версия плана загрузки
     */
    @Column(name = "plan_id", nullable = false)
    private Long planId;

    /**
     * Номер дела (ЕРДР)
     */
    @Column(name = "case_no", nullable = false)
    private String caseNo;

    /**
     * Идентификатор надзорного производства
     */
    @Column(name = "registry_id")
    private Long registryId;

    /**
     * UUID файла из источника (sc.get_case_documents).
     * Уникален в рамках плана
     */
    @Column(name = "file_identifier", nullable = false)
    private UUID fileIdentifier;

    /**
     * UUID запроса/пакета передачи из источника
     */
    @Column(name = "request_identifier", nullable = false)
    private UUID requestIdentifier;

    /**
     * Идентификатор карточки TE2
     */
    @Column(name = "te2_card_id", nullable = false)
    private String te2CardId;

    /**
     * Путь к файлу в Jackrabbit (JCR)
     */
    @Column(name = "jsr_path")
    private String jsrPath;

    /**
     * Порядковый номер документа в источнике
     */
    @Column(name = "order_index")
    private Integer orderIndex;

    /**
     * Оригинальное имя документа из источника
     */
    @Column(name = "document_name")
    private String documentName;

    /**
     * ID типа документа
     */
    @Column(name = "doc_type_id")
    private Long docTypeId;

    /**
     * Код типа документа
     */
    @Column(name = "doc_type_code")
    private String docTypeCode;

    /**
     * Наименование типа документа (RU)
     */
    @Column(name = "doc_type_name_ru")
    private String docTypeNameRu;

    /**
     * Наименование типа документа (KK)
     */
    @Column(name = "doc_type_name_kk")
    private String docTypeNameKk;

    /**
     * ID спецификации (вид) документа
     */
    @Column(name = "doc_spec_id")
    private Long docSpecId;

    /**
     * Код спецификации (вид) документа
     */
    @Column(name = "doc_spec_code")
    private String docSpecCode;

    /**
     * Наименование спецификации (вида) документа (RU)
     */
    @Column(name = "doc_spec_name_ru")
    private String docSpecNameRu;

    /**
     * Наименование спецификации (вида) документа (KK)
     */
    @Column(name = "doc_spec_name_kk")
    private String docSpecNameKk;

    /**
     * ID квалификации
     */
    @Column(name = "qualification_id")
    private String qualificationId;

    /**
     * Код квалификации
     */
    @Column(name = "qualification_code")
    private String qualificationCode;

    /**
     * Наименование квалификации (RU)
     */
    @Column(name = "qualification_name_ru")
    private String qualificationNameRu;

    /**
     * Наименование квалификации (KK)
     */
    @Column(name = "qualification_name_kk")
    private String qualificationNameKk;

    /**
     * Дата отправки документа из источника
     */
    @Column(name = "send_date")
    private LocalDateTime sendDate;

    /**
     * Основной префикс для файлов в S3
     */
    @Column(name = "s3_main_prefix")
    private String s3MainPrefix;

    /**
     * Путь к оригинальному файлу S3/MinIO
     */
    @Column(name = "s3_file_path_original")
    @Enumerated(EnumType.STRING)
    private UploadPlanItemFilePathType s3FilePathOriginal;

    /**
     * Имя оригинального файла S3/MinIO
     */
    @Column(name = "s3_file_name_original")
    private String s3FileNameOriginal;

    /**
     * Расширение файла, сохранённого в S3/MinIO
     */
    @Column(name = "s3_file_ext_original", length = 10)
    private String s3FileExtOriginal;

    /**
     * MIME-тип файла в S3/MinIO
     */
    @Column(name = "s3_mime_type_original")
    private String s3MimeTypeOriginal;

    /**
     * Путь к сконвертированному файлу S3/MinIO
     */
    @Column(name = "s3_file_path_converted")
    @Enumerated(EnumType.STRING)
    private UploadPlanItemFilePathType s3FilePathConverted;

    /**
     * Имя сконвертированного файла S3/MinIO
     */
    @Column(name = "s3_file_name_converted")
    private String s3FileNameConverted;

    /**
     * Путь к обработанному файлу S3/MinIO
     */
    @Column(name = "s3_file_path_processed")
    @Enumerated(EnumType.STRING)
    private UploadPlanItemFilePathType s3FilePathProcessed;

    /**
     * Имя обработанного файла S3/MinIO
     */
    @Column(name = "s3_file_name_processed")
    private String s3FileNameProcessed;

    /**
     * Операционный статус обработки файла
     */
    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    private UploadPlanItemStatus status;

    /**
     * Дата последнего изменения статуса
     */
    @Column(name = "status_changed_at", nullable = false)
    private LocalDateTime statusChangedAt;

    /**
     * Описание последней ошибки обработки файла
     */
    @Column(name = "error_message")
    private String errorMessage;

    /**
     * Дата создания записи
     */
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    /**
     * Дата последнего обновления записи
     */
    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    /**
     * Флаг: доступен файл для загрузки
     */
    @Column(name = "jr_file_exist")
    private Boolean jrFileExist;

    /**
     * Размер файла
     */
    @Column(name="jr_file_size")
    private Long jrFileSize;

    /**
     * mime-type в JR
     */
    @Column(name = "jr_mime_type")
    private String jrMimeType;

    /**
     * Версия для оптимистичной блокировки (JPA @Version)
     */
    @Version
    @Column(name = "version", nullable = false)
    private Long version;

    /**
     * Количество попыток обработки (скачивания/загрузки в S3) данного файла
     */
    @Column(name = "attempt_count", nullable = false)
    private Integer attemptCount;

    /**
     * Момент времени, когда запись снова может быть взята в обработку после ошибки
     */
    @Column(name = "next_retry_at")
    private LocalDateTime nextRetryAt;

    @PrePersist
    public void prePersist() {
        LocalDateTime now = LocalDateTime.now();
        this.createdAt = now;
        this.updatedAt = now;
        this.statusChangedAt = now;
    }

    @PreUpdate
    public void preUpdate() {
        this.updatedAt = LocalDateTime.now();
    }
}