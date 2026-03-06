package kz.gp.model.entity.primary;

/**
 * Статус обработки плана
 */
public enum UploadPlanStatus {

    CREATED,
    PROCESSING,
    UPLOADED,
    CONVERTED,
    COMPLETED,
    COMPLETED_WITH_ERRORS,
    FAILED
}
