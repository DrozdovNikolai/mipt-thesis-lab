# 55north Backend

Серверное API системы «55 Север» на Go. Оно обслуживает каталоги пилотов, сценарии и расписания тренировок, хранит оценки экипажа и формирует PDF-отчёты. Для работы нужны PostgreSQL и Redis.

- [Архитектура и карта модулей](docs/BACKEND_ARCHITECTURE.md)
- [Сборка, настройки и запуск в Docker](deploy/README.md)
- [Схема PostgreSQL](deploy/schema.sql)
- [Обработка исторических статусов тренировок](docs/SUBMISSION_STATUS.md)

## Локальная проверка

В каталоге `backend/` выполните:

```bash
go test ./...
go build ./...
```
