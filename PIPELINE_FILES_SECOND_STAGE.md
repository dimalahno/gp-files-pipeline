Отлично 👍
У тебя уже зрелый Stage 1 (DB-driven orchestration + S3 + retry + versioning).
Теперь аккуратно проектируем **Stage 2 — Conversion Pipeline**.

Работаем строго в твоей архитектуре:
PostgreSQL = очередь, S3 = файловое хранилище, статусы = state machine.

---

# 📌 Stage 2 — Конвертация файлов в TXT + извлечение метаданных

## 🎯 Цель этапа

Для файлов со статусом `UPLOADED`:

1. Скачать файл из S3
2. Извлечь текст (pdf/doc/docx, включая OCR)
3. Сохранить:

   * TXT файл в S3
   * Метаданные в БД
4. Перевести статус в `CONVERTED`

---

# 🗄 1. Изменения в БД

### Расширяем status:

```
CREATED
DOWNLOADING
UPLOADED
CONVERTING        ← новое
CONVERTED         ← новое
PROCESSED
ERROR
```

---

### 📋 Новые поля в upload_plan_item

| Поле                  | Тип     | Назначение               |
| --------------------- | ------- | ------------------------ |
| text_s3_path          | text    | путь к txt в S3          |
| text_size             | bigint  | размер текста            |
| page_count            | int     | кол-во страниц           |
| has_ocr               | boolean | применялся ли OCR        |
| text_extracted        | boolean | удалось ли извлечь текст |
| convert_attempt_count | int     | retry конвертации        |
| convert_error         | text    | ошибка конвертации       |

---

# ⚙ 2. Архитектура Stage 2

Архитектура **полностью повторяет Stage 1**, но с отдельным worker.

### Компоненты:

* `PlanItemConvertDispatcher`
* `ItemConvertWorker`
* `ThreadPoolTaskExecutor (2-4 потока)`
* `S3Service`
* `TextExtractionService`

---

# 🔄 3. Логика обработки

## 3.1 Dispatcher

Каждые 5 секунд:

```sql
SELECT *
FROM upload_plan_item
WHERE status = 'UPLOADED'
  AND convert_attempt_count < 5
  AND (next_retry_at IS NULL OR next_retry_at < NOW())
FOR UPDATE SKIP LOCKED
LIMIT 5;
```

Переводим в:

```
status = CONVERTING
```

---

## 3.2 Worker — основной сценарий

### Шаг 1 — Скачать файл из S3

---

### Шаг 2 — Определить тип файла

* pdf
* doc
* docx

---

# 🧠 4. Извлечение текста

Разбиваем на два сценария:

---

## 📄 PDF

### A) Text-based PDF

Используем:

* pdfplumber / PyMuPDF
* Apache Tika (альтернатива)

Если текст > N символов → считаем успешным.

---

### B) Scanned PDF (нет text layer)

Признак:

* извлечённый текст пустой
* очень мало символов

Тогда:

1. Конвертируем страницы в изображения
2. OCR через Tesseract
3. Собираем текст

```
has_ocr = true
```

---

## 📄 DOC / DOCX

### DOCX

* python-docx
* mammoth
* Apache Tika

---

### Старый DOC (binary)

Лучше всего:

* LibreOffice headless → convert to docx
* затем извлекать

---

### Грязные DOC / PDF

Если структура повреждена:

1. Пробуем Tika
2. Если не удалось → ERROR
3. Retry max 5

---

# 💾 5. Сохранение результата

## 5.1 TXT файл

S3 структура:

```
/converted/{plan_id}/{item_id}.txt
```

---

## 5.2 Метаданные в БД

Сохраняем:

* text_s3_path
* text_size
* page_count
* has_ocr
* text_extracted = true
* convert_attempt_count++
* status = CONVERTED

---

# 🔐 6. Retry логика

Аналог Stage 1:

* max 5 попыток
* exponential backoff
* next_retry_at
* optimistic locking

---

# 🧱 7. Структура Python сервиса

```
gp-files-pipeline
│
├── app
│   ├── main.py
│   ├── config.py
│   │
│   ├── dispatcher
│   │     convert_dispatcher.py
│   │
│   ├── workers
│   │     convert_worker.py
│   │
│   ├── extraction
│   │     pdf_extractor.py
│   │     doc_extractor.py
│   │     ocr_service.py
│   │
│   ├── storage
│   │     s3_client.py
│   │
│   ├── db
│   │     models.py
│   │     repository.py
│   │
│   └── api
│         routes.py
│
├── Dockerfile
└── requirements.txt
```

---

# 🧮 8. Поток обработки

```
UPLOADED
   ↓
CONVERTING
   ↓
CONVERTED
   ↓
(далее Stage 3 — извлечение сущностей)
```

---

# 🚨 9. Подводные камни (важно)

## ⚠ 1. Память

PDF 300MB + OCR = OOM
Решение:

* потоковая обработка
* page-by-page
* ограничение размера

---

## ⚠ 2. Кодировки

DOCX → UTF-8
PDF → могут быть битые символы
Нужна нормализация Unicode.

---

## ⚠ 3. Многоязычность

Ты работаешь с RU + KZ.

Tesseract нужно установить языки:

```
rus
kaz
eng
```

---

## ⚠ 4. Производительность OCR

OCR = очень тяжёлый этап
Лучше:

* ограничить 1–2 потока
* либо вынести OCR в отдельный сервис

---

# 🏗 Рекомендуемая стратегия

1️⃣ Сначала реализовать без OCR
2️⃣ Добавить fallback OCR
3️⃣ Добавить метрики (pages/sec, OCR_time)

---

# 🧭 Итоговая схема Stage 2

```
S3 (original)
      ↓
Convert Dispatcher (DB queue)
      ↓
Worker
      ↓
Text extraction
      ↓
S3 (txt)
      ↓
DB meta update
      ↓
CONVERTED
```

---
