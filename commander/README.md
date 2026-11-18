# 55north Commander

Commander — веб-приложение на Vue 3 и TypeScript для работы с профилями пилотов, тренировками, отчётами, аналитикой и настройками совместимости экипажа.

## Локальный запуск

Требуется Node **24.21.0** (см. `.nvmrc`).

```bash
nvm use
npm ci
COMMANDER_API_PROXY=http://127.0.0.1:8812 npm run dev
```

`COMMANDER_API_PROXY` — адрес вашего API для Vite dev proxy. Браузер обращается к `/api`; proxy сохраняет этот префикс. Другой публичный base URL можно задать через `VITE_API_URL` в `.env.local`; сервер должен разрешать соответствующий origin. Пример публичных настроек — `.env.example`. Секреты в `VITE_*` не помещать: они попадают в клиентскую сборку.

```bash
npm run format:check
npm run lint
npm run test:unit
npm run build:55nord
npx playwright install chromium
COMMANDER_TEST_PREVIEW=1 npm run test:e2e
```

`build` включает проверку типов. E2E по умолчанию запускают Vite; `COMMANDER_TEST_PREVIEW=1` использует уже собранный `dist`. `COMMANDER_TEST_BASE_URL` позволяет проверить работающий static server. Тесты используют синтетические API fixtures; подключать их к настоящему API не следует. Для реального изолированного API предусмотрен отдельный `npm run test:e2e:api`; для Firefox/WebKit — `npm run test:browsers`.

После сборки `npm run test:visual` проверяет экраны при разной ширине окна, а `npm run test:performance` измеряет время загрузки страниц пилотов и аналитики. Результаты сохраняются в `test-results/`.

## Сборка и размещение

```bash
docker compose -f deploy/compose.yml up -d --build
```

Пример слушает `127.0.0.1:8088`, API по умолчанию проксируется на `host.docker.internal:8812`. Параметры: `COMMANDER_API_ORIGIN`, `COMMANDER_PORT`, `COMMANDER_IMAGE`, `VITE_APP_VERSION`. Nginx обслуживает nested SPA routes и отдельно обрабатывает `/api` и отсутствующие assets. Для рабочего размещения используйте проверенный неизменяемый image tag и существующий HTTPS reverse proxy.

## Сессии и права доступа

Права проверяются через `/auth/me`; сохранённые privileges не разрешают доступ до ответа API. Refresh синхронизируется между вкладками через Web Locks на HTTPS/localhost. Cache и черновики очищаются при смене сессии. Запись настроек требует фактического backend-права `pilots:write`; чтение раздела — `pilots:read`.
