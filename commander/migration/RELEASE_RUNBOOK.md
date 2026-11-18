# Проверка, размещение и откат Commander

Эта процедура подготовлена для переноса frontend без изменения backend. Production destination не задан. Рабочие сервисы `firefly-backend` и их данные не используются для разрушающих тестов.

## Текущий локальный preview

На этой рабочей машине открыт **http://localhost:8088**: Nginx, Vue 55nord и отдельный настоящий API с синтетическими пилотами. Вход: `admin` / `commander-integration-only`. Контейнер frontend — `north55-commander-preview`, release root — `/home/kolya/.cache/55north-commander-migration/releases-20261008`. Это локальная среда приёмки, а не выбранный production/staging.

SHA-256 manifests установленных artifacts сохранены в [evidence/m9/releases](evidence/m9/releases). Активен `vue-55nord-m9-bootstrap`; `vue-firefly-m9-bootstrap` и `react-baseline` установлены для rehearsal. Предыдущие Vue releases сохранены вместе с hashed assets. Тестовый API — `127.0.0.1:8898`, его PostgreSQL/Redis принадлежат compose project `north55-commander-integration`.

## Проверенные команды проекта

```bash
nvm use
npm ci
npm run format:check
npm run lint
npm run test:unit
npm run build:55nord
npx playwright install --with-deps chromium firefox webkit
COMMANDER_TEST_PREVIEW=1 npm run test:e2e
npm run test:browsers
npm run build:firefly
COMMANDER_TEST_PREVIEW=1 npm run test:e2e
```

CI выполняет install/checks/build/E2E для обоих брендов. Firefox/WebKit smoke обязателен для 55nord. `VITE_APP_VERSION` берётся из commit SHA; успешная проверка публикует отдельный artifact каждого бренда. Workflow не содержит неизвестных адресов deploy и не публикует сайты автоматически. Его remote execution и branch protection нужно настроить после указания Git remote.

Не пересобирать release после приёмки: скачивается и размещается тот же `dist` artifact. Публичные `VITE_*` задаются до build; API proxy origin задаётся Nginx при запуске. Секретные серверные переменные в frontend не передаются.

## Изолированный настоящий API

`migration/backend/compose.yml` создаёт отдельные PostgreSQL/Redis/API. PostgreSQL хранится в tmpfs; остановка/пересоздание базы предназначено только для этих синтетических данных. API слушает `127.0.0.1:8898`. Соседний `../firefly-backend` монтируется read-only, его `.env` не используется.

Если тестового image нет, собрать собственный dependency image из соседнего backend:

```bash
docker build --build-arg INSTALL_DEV=1 \
  -t 55north-commander-backend:fixture ../firefly-backend
export COMMANDER_BACKEND_TEST_IMAGE=55north-commander-backend:fixture
docker compose -f migration/backend/compose.yml up -d --wait api
docker compose -f migration/backend/compose.yml run --rm --no-deps api \
  python /smoke/seed.py > migration/evidence/m9/backend-fixture.json
```

Seed запускается один раз на свежей БД. Он использует только synthetic fixture builders; pytest schema-reset fixtures не запускаются. Тестовый login — `admin`, password — `commander-integration-only`, только в этой изолированной БД. Этот пароль не является credential рабочего backend.

Nginx подключается к сети `north55-commander-integration_browser` и проксирует `COMMANDER_API_ORIGIN=http://api:8000`. После запуска frontend:

```bash
COMMANDER_INTEGRATION_URL=http://127.0.0.1:8088 npm run test:e2e:api
```

Integration tests не используют API mocks и не сохраняют session tokens в trace/screenshot. Rehearsal test пропускается, если не задан специально подготовленный disposable release root. Для завершения локального стенда остановить только его frontend container и выполнить `docker compose -f migration/backend/compose.yml down`.

## Проверки настоящих вкладок, zoom и confirm

После запуска этого локального preview/API, в окружении с графическим display и установленным Playwright Chromium:

```bash
npm run test:native-tabs
```

Команда использует только `http://127.0.0.1:8088` и синтетические credentials стенда. Она запускает собственный Chrome с временным профилем, создаёт две вкладки в одном окне, проверяет `hidden → visible`, изменяет размеры окна в фоне и сравнивает восстановленные pixels шести canvas аналитики/профиля. Браузер и профиль удаляются в `finally`; чужие окна не затрагиваются. Результаты — `migration/evidence/m9/native-tabs/results.json` и raw canvas PNG.

Обычный Playwright включает focus emulation и не подтверждает этот сценарий даже с `--headed`. Здесь используется direct CDP без подмены Page Visibility.

В Linux/X11 (включая WSLg) с `xdotool` дополнительно запустить:

```bash
npm run test:native-zoom
```

При нестандартном пути к `xdotool` задать `COMMANDER_XDOTOOL`. Этот вариант сначала повторяет hidden-tab cases, затем отправляет пять Ctrl+Plus только окну собственного browser PID. Он подтверждает удвоение DPR/уменьшение viewport вдвое без pinch/CSS emulation, проходит восемь основных страниц, проверяет доступность активных controls через focus/scroll/hit testing и сохраняет screenshots/results в `migration/evidence/m9/native-zoom`. Нужны системные browser libraries и X11; это отдельная графическая приёмка, не шаг headless CI. Native Escape и возврат фокуса в confirm проверяются отдельно:

```bash
npm run test:native-confirm
```

Нужен тот же `xdotool`. Сценарий создаёт один отдельный тип в synthetic API, открывает confirm настоящим browser click, отправляет Escape в собственное окно, проверяет возврат фокуса и отсутствие mutation. `finally` удаляет только созданный тип. Отчёт — `migration/evidence/m9/native-confirm/results.json`. Сценарий не предназначен для рабочего API; он использует фиксированный localhost-стенд и его тестовый пароль.

Native popup/print и пользовательский pilot остаются отдельными проверками.

## Atomic release layout

```text
/srv/commander/
  assets/                  # объединение неизменяемых hashed assets
  releases/
    react-baseline/
    vue-<release-id>/
  current -> releases/vue-<release-id>
```

Nginx-конфигурация — [releases.conf.template](../deploy/releases.conf.template). Монтируется весь `/srv/commander`, чтобы изменение symlink было видно без пересоздания контейнера. `/api` отдельно проксируется; отсутствующие static assets возвращают 404; HTML имеет `no-store`, hashed assets — immutable cache.

Пример установки проверенного artifact:

```bash
python3 deploy/release.py --root /srv/commander \
  --release vue-<release-id> --source /path/to/verified-dist
python3 deploy/release.py --root /srv/commander \
  --release vue-<release-id> --activate
```

`release.py` запрещает повторное использование ID и конфликт содержимого hashed asset; сохраняет SHA-256 manifest, проверяет байты перед активацией и атомарно заменяет symlink. Он не очищает старые assets и не изменяет backend.

Откат:

```bash
python3 deploy/release.py --root /srv/commander \
  --release react-baseline --activate
```

Для автоматического локального rehearsal создать в специальном тестовом root файл `.commander-disposable-rehearsal`, установить туда `react-baseline`, `vue-55nord-m9`, `vue-firefly-m9`, подключить root к тестовому Nginx и задать `COMMANDER_REHEARSAL_ROOT`. Не создавать этот marker в production release root. Для других установленных ID использовать `COMMANDER_REHEARSAL_55NORD_RELEASE` и `COMMANDER_REHEARSAL_FIREFLY_RELEASE`; на текущем стенде это `vue-55nord-m9-bootstrap` и `vue-firefly-m9-bootstrap`.

Rehearsal проверяет: обновление Vue token pair через настоящий API → переключение на React → загрузку старого lazy chunk в открытой Vue-вкладке → reload React без нового login → переключение бренда Firefly → восстановление 55nord. Локальный прогон уложился в секунды при ориентире отката до 10 минут. Это не измерение времени операции на ещё не выбранном production host.

## Перед production

Необходимы конкретные domain/server/path, brand, API URL/version, Git remote, Sentry DSN при использовании monitoring, pilot group и согласованный rollback window. Эти значения не выводятся из имён соседних репозиториев.

1. Повторить smoke на целевом preview с synthetic tenant, включая права read/write, реальные media и PDF.
2. Человеку проверить print dialog/закрытие окна, popup blocking и основные операции пилотной группы. Headless PDF Blob и CSS reflow не заменяют эти проверки.
3. Переключить только frontend на проверенный artifact; backend остаётся прежним.
4. Проверить root/deep links, brand/favicon, login/refresh, профиль, выбранный assessment PDF, Settings и Compatibility. Проверить доставку monitoring event с нужным release tag, если DSN настроен.
5. Наблюдать не менее согласованного периода (план предлагает два рабочих дня). При массовых auth failures, неверном пользователе/assessment, ошибочных Settings writes или недоступности ключевых экранов вернуть прежний frontend.
6. Сохранить React artifact и общие assets до конца rollback window. Frontend rollback не отменяет выполненные через прежний API изменения данных.

## Доказательства

Основные ссылки — [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md), [матрица](acceptance-matrix.md), `evidence/m9/*`. Исторические failed logs оставлены для объяснения исправлений; актуальный pass нужно проверять по соответствующему финальному прогону. Raw screenshots являются материалом сравнения, а не автоматическим одобрением всех визуальных различий.
