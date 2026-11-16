# Запуск 55north Backend

Для API нужны PostgreSQL, Redis и файловое хранилище.

## Сборка

Из корня репозитория:

```bash
docker build -t 55north-backend:local .
```

Dockerfile закрепляет Go 1.27.1 и digest builder/runtime images. Runtime использует
`static-debian13:nonroot`; описание вариантов — в
[официальном Distroless README](https://github.com/GoogleContainerTools/distroless).
Builder компилирует статические Go-бинарники со встроенными шрифтами.

## Окружение и хранилище

Скопируйте `.env.example` в `.env` и задайте существующие PostgreSQL/Redis,
JWT keys, настройки capability/allowlists, client origins и storage.
При переключении сохраняются прежние JWT keys и media/S3 prefixes.
`LoadConfig` читает environment процесса; `.env` передаёт Compose.

Compose использует подготовленные external network и volumes. До старта проверьте
перенос имеющихся media/feedback и права UID/GID `65532:65532`. Локальные paths
в контейнере находятся в `/var/lib/55north/`; имена объектов/подкаталогов сохраняются.
Для S3 задайте `FILE_STORAGE_BACKEND=s3` и те же bucket/prefix/region/credentials.
Local fallback и dual write задаются отдельно.

Запуск:

```bash
docker compose --env-file .env -f deploy/compose.yml config --quiet
docker compose --env-file .env -f deploy/compose.yml up -d --wait
```

Порт по умолчанию слушает `127.0.0.1`; внешний reverse proxy и домен настраиваются
для существующего API URL. API подключается к подготовленной базе. Схема PostgreSQL хранится в [schema.sql](schema.sql).

## Probes, файлы и завершение

Healthcheck проверяет JSON `status=ready`, поскольку `/health/ready` возвращает
HTTP 200 и при `degraded`. `55north-healthcheck live` проверяет liveness отдельно.
Оба probe учитывают `PORT` и `API_PREFIX`, включая `/v2`.

Root filesystem доступна только для чтения. `/tmp` находится в tmpfs: multipart
parser переносит файлы больше 1 МиБ на диск; storage fallback также использует
временные файлы. Размер tmpfs — 256 МиБ, требует проверки на ожидаемой нагрузке.
Media/feedback доступны для записи; backup volume подключён только для чтения.
API проверяет наличие backups, но не создаёт их: backup/restore выполняет отдельный
job PostgreSQL и средства копирования media/S3.

Compose оставляет 25 секунд на SIGTERM: HTTP shutdown ограничен 15 секундами,
Sentry flush — ещё двумя. На синтетическом стенде idle shutdown вернул exit 0.

## Исторические статусы

Команда в образе запускается с отдельным entrypoint:

```bash
docker compose --env-file .env -f deploy/compose.yml run --rm --no-deps \
  -e NORTH55_MIGRATION_DATABASE_URL \
  --entrypoint /usr/local/bin/migrate-submission-state api -action plan
```

Перед командой явно задайте `NORTH55_MIGRATION_DATABASE_URL` для выбранной
копии/целевой БД в environment shell. Команда не использует `DATABASE_URL`
автоматически. Применение требует просмотренного plan hash и run ID; порядок, блокировки и
rollback описаны в
[контракте перехода](../docs/SUBMISSION_STATUS.md).
Автоматического применения при старте API нет.
Для просмотренного набора записей v2 поддерживает `-training-ids '<ID>,<ID>'`.
Этот список входит в plan hash и журнал; передайте его также при apply/повторе.
