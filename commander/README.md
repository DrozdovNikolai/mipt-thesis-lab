# 55north Commander

Фронтенд Commander на Vue 3, TypeScript, Pinia и Vue Query. Перенесены маршруты и бизнес-функции React-приложения из `../firefly-commander`: пилоты и профиль, тренировки с отчётами, аналитика, настройки порогов и совместимость экипажа. Исходный React-репозиторий не изменяется.

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
npm run build:firefly
```

`build` включает проверку типов. E2E по умолчанию запускают Vite; `COMMANDER_TEST_PREVIEW=1` использует уже собранный `dist`. `COMMANDER_TEST_BASE_URL` позволяет проверить работающий static server. Тесты используют синтетические API fixtures; подключать их к настоящему API не следует. Для реального изолированного API предусмотрен отдельный `npm run test:e2e:api`; для Firefox/WebKit — `npm run test:browsers`. Команды подготовки окружений — в release runbook.

`npm run test:visual` и `npm run test:performance` сравнивают React reference на порту 4176 и Vue production preview на 4177. Reference восстанавливается из `source-inventory.json`; исходный React-репозиторий сохраняется отдельно.

## Сборка и размещение

```bash
docker compose -f deploy/compose.yml up -d --build
```

Пример слушает `127.0.0.1:8088`, API по умолчанию проксируется на `host.docker.internal:8812`. Параметры: `COMMANDER_API_ORIGIN`, `COMMANDER_PORT`, `COMMANDER_IMAGE`, `COMMANDER_BRAND`, `VITE_APP_VERSION`. Nginx обслуживает nested SPA routes и отдельно обрабатывает `/api` и отсутствующие assets. Для рабочего размещения используйте проверенный неизменяемый image tag и существующий HTTPS reverse proxy.

## Миграция и приёмка

- [Исходный comprehensive plan](MIGRATION_PLAN.md)
- [Текущее состояние реализации и оставшиеся проверки](migration/IMPLEMENTATION_STATUS.md)
- [Принятые решения и исправления](migration/DECISIONS_AND_FIXES.md)
- [Размещение, изолированный API и откат](migration/RELEASE_RUNBOOK.md)
- [Матрица приёмки](migration/acceptance-matrix.md)
- [Зафиксированный source inventory](migration/source-inventory.json)
- [Результаты React baseline](migration/evidence/m0/)
- [Первый успешный прогон исходных пяти E2E на Vue](migration/evidence/m3-m6/checks.json)

`session-store` сохраняет совместимый с React envelope. Права проверяются через `/auth/me`; сохранённые privileges не разрешают доступ до ответа API. Refresh синхронизируется между вкладками через Web Locks на HTTPS/localhost. Cache и черновики очищаются при смене сессии. Запись настроек требует фактического backend-права `pilots:write`; чтение раздела — `pilots:read`.
