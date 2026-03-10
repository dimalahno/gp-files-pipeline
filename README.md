# Сервис расчёта наказаний
Python version: 3.11

## Описание сервиса
- **name:** gp-files-pipeline
- **port:** 9001
- **context-path:** /files/pipeline
- **actuator:** http://gp-files-pipeline.gosobvin.kz:31056/api/gp/v1/files/pipeline/health
- **swagger:** http://gp-files-pipeline.gosobvin.kz:31056/docs

Сервис реализует Stage 2 пайплайна обработки файлов:
`UPLOADED -> CONVERTING -> CONVERTED`.

### Что делает Stage 2
1. Забирает из БД элементы `upload_plan_item` со статусом `UPLOADED`.
2. Блокирует batch через `FOR UPDATE SKIP LOCKED`.
3. Переводит элементы в `CONVERTING`.
4. Worker скачивает исходный файл из MinIO/S3.
5. Извлекает текст (`pdf`, `docx`; `doc` — с ошибкой и retry до конвертации во внешнем сервисе).
6. Сохраняет txt в S3: `converted/{plan_id}/{item_id}.txt`.
7. Пишет метаданные и переводит статус в `CONVERTED`.
8. При ошибке: `ERROR`, `convert_attempt_count++`, backoff по `next_retry_at`.

## Локальный запуск

### 1) Установка зависимостей
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Настройка переменных окружения
Все параметры можно переопределить через переменные с префиксом `APP_`.
Пример:
```bash
export APP_DB_URL='postgresql+psycopg2://postgres:postgres@localhost:5432/gp_cases_db'
export APP_MINIO_ENDPOINT='http://localhost:9000'
export APP_MINIO_BUCKET='gosobvin'
export APP_MINIO_ACCESS_KEY='admin'
export APP_MINIO_SECRET_KEY='minio12345'
```
### 3) Запуск
```bash
uvicorn app.main:app --host 0.0.0.0 --port 9001
```

## Docker

### Сборка
```bash
docker build -t gp-files-pipeline .
```

### Запуск
```bash
docker run --rm -p 9001:9001 gp-files-pipeline
```

## API
- `GET /files/pipeline/health` — health check.
- `POST /files/pipeline/dispatch/convert` — ручной запуск одного цикла диспетчера.

- Проверка в браузере (swagger): http://localhost:9001/docs

## Запуск локально контейнера 
- Сборка: 
```docker build -t gp-files-pipeline-service .```
- Запуск:
``` docker run -p 9001:9001 gp-files-pipeline-service```
- Пересборка:
``` docker build -t gp-files-pipeline-service .```
- Остановить контейнер:
```
docker ps
docker stop <container_id>
```