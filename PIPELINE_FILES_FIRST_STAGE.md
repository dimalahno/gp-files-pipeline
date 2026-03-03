# 📌 Справка по реализации сервиса загрузки файлов (Stage 1)

## 1. Назначение сервиса

Реализован backend-сервис (Java 21 / Spring Boot 3.3.4) для:

* получения upload-плана
* сохранения плана и элементов в PostgreSQL
* асинхронной загрузки файлов из Apache JackRabbit
* сохранения файлов в S3 (MinIO)
* управления статусами обработки

---

# 🗄 2. База данных (PostgreSQL)

Таблица: `files_storage.upload_plan_item`

### Добавлены поля:

* `attempt_count integer not null default 0`
* `next_retry_at timestamp`
* `version bigint not null default 0` (optimistic locking)
* расширен `status` → добавлен `DOWNLOADING`

### Статусы элемента:

```
CREATED
DOWNLOADING
UPLOADED
PROCESSED
ERROR
```

### Назначение:

| Поле          | Назначение             |
| ------------- | ---------------------- |
| attempt_count | контроль retry         |
| next_retry_at | backoff-политика       |
| version       | защита от гонок        |
| status        | state machine элемента |

---

# ⚙ 3. Архитектура обработки

Используется DB-driven orchestration (PostgreSQL как очередь).

### Компоненты:

* `PlanItemDownloadDispatcher`
* `ItemDownloadWorker`
* `ThreadPoolTaskExecutor (2 потока)`
* `UploadPlanItemRepository`
* `JackrabbitFileService`
* `FileStorageServicePrimary (S3/MinIO)`

---

# 🔄 4. Логика работы

## 4.1 Dispatcher

`@Scheduled(fixedDelay = 5000)`

Один раз в 5 секунд:

1. Проверяет свободные потоки
2. Выбирает batch через:

```sql
FOR UPDATE SKIP LOCKED
```

3. Переводит записи в `DOWNLOADING`
4. Передаёт itemId в Executor

БД используется как безопасная очередь.

---

## 4.2 Worker (ItemDownloadWorker)

Обрабатывает один элемент:

1. Загружает файл из JackRabbit по `jsr_path`
2. Потоково передаёт файл в MinIO
3. Обновляет:

   * `status = UPLOADED`
   * `s3_file_path`
   * `s3_file_name`
   * `attempt_count++`

При ошибке:

* `status = ERROR`
* сохраняется `error_message`
* рассчитывается `next_retry_at`
* retry ограничен (max 5)

---

# 🧵 5. Потоки

ThreadPool:

```
corePoolSize = 2
maxPoolSize = 2
queueCapacity = 0
```

Ограничение сделано намеренно, чтобы не перегружать JackRabbit.

---

# 🔐 6. Гарантии устойчивости

* `FOR UPDATE SKIP LOCKED` — защита от повторной обработки
* Optimistic locking (`@Version`)
* Retry-механизм
* Backoff-политика
* Отсутствие in-memory очередей
* Без Kafka / Redis

PostgreSQL выполняет роль внутренней шины.

---

# 📊 7. Текущий статус реализации

Реализовано:

* DDL обновление таблицы
* Entity с `@Version`
* Repository с lock batch
* Dispatcher с @Scheduled
* Worker с транзакционной обработкой
* Интеграция:

  * Apache JackRabbit
  * MinIO (S3)

---

# 🎯 Результат

Сервис способен:

* принимать план
* асинхронно скачивать 170+ файлов
* безопасно обрабатывать ошибки
* выдерживать рестарт приложения
* работать без внешнего брокера сообщений

---

Следующий этап логично реализовать:

**Stage 2 — Python сервис конвертации (UPLOADED → CONVERTED → PROCESSED)**


