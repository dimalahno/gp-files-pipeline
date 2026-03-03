# Сервис расчёта наказаний

## Описание сервиса
- **name:** gp-files-pipeline
- **port:** 9001
- **context-path:** /files/pipeline
- **actuator:** http://gp-files-pipeline.gosobvin.kz:31056/api/gp/v1/files/pipeline/health
- **swagger:** http://gp-files-pipeline.gosobvin.kz:31056/docs

## Запуск локально контейнера 
- Сборка: 
```docker build -t gp-files-pipeline .```
- Запуск:
``` docker run -p 9001:9001 gp-files-pipeline```
- Пересборка:
``` docker build -t gp-files-pipeline .```
- Остановить контейнер:
```
docker ps
docker stop <container_id>
```
- Проверка в браузере (swagger): http://localhost:9001/docs