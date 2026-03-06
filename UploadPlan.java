package kz.gp.model.entity.primary;

import jakarta.persistence.Entity;
import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;

@Entity
@Table(
        name = "upload_plan",
        schema = "files_storage",
        uniqueConstraints = {
                @UniqueConstraint(
                        name = "upload_plan_case_version_uq",
                        columnNames = {"case_no", "version"}
                )
        }
)
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class UploadPlan {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Идентификатор надзорного производства.
     */
    @Column(name = "registry_id")
    private Long registryId;

    /**
     * Номер дела ЕРДР, по которому сформирован план.
     */
    @Column(name = "case_no", nullable = false)
    private String caseNo;

    /**
     * Статус плана: CREATED/PROCESSING/COMPLETED/COMPLETED_WITH_ERRORS/FAILED.
     */
    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    private UploadPlanStatus status;

    /**
     * JSON-план в виде текста. Источник истины для воспроизведения/повтора.
     */
    @Column(name = "plan_json", nullable = false, columnDefinition = "TEXT")
    private String planJson;

    /**
     * Хэш плана (например sha256) для идемпотентности/сравнения одинаковых планов.
     */
    @Column(name = "plan_hash")
    private String planHash;

    /**
     * Версия плана в рамках одного case_no.
     */
    @Version
    @Column(name = "version", nullable = false)
    private Integer version = 1;

    /**
     * Количество элементов (файлов) в плане.
     */
    @Column(name = "total_items", nullable = false)
    private Integer totalItems = 0;

    /**
     * Количество элементов, завершённых успешно.
     */
    @Column(name = "done_items", nullable = false)
    private Integer doneItems = 0;

    /**
     * Количество элементов, завершённых с финальной ошибкой.
     */
    @Column(name = "failed_items", nullable = false)
    private Integer failedItems = 0;

    /**
     * Дата/время создания записи плана.
     */
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    /**
     * Дата/время последнего обновления записи плана.
     */
    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    /**
     * Ошибка уровня плана (не по отдельным файлам).
     */
    @Column(name = "last_error", columnDefinition = "TEXT")
    private String lastError;

    @PrePersist
    public void prePersist() {
        LocalDateTime now = LocalDateTime.now();
        this.createdAt = now;
        this.updatedAt = now;
    }

    @PreUpdate
    public void preUpdate() {
        this.updatedAt = LocalDateTime.now();
    }
}
