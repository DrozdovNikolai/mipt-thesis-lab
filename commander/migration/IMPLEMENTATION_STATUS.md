# Ход реализации

Обновлено 8 октября 2026 года. Перенос приложения реализован; M9 — приёмка, M10 — выпуск — ещё не завершены. Production не переключён.

Локальный preview: **http://localhost:8088**, вход `admin` / `commander-integration-only`. Он использует отдельную синтетическую БД. Подготовка, release manifests и откат описаны в [RELEASE_RUNBOOK.md](RELEASE_RUNBOOK.md).

## Подтверждено

- Vue 3, strict TypeScript, Pinia, Vue Query, Vue Router, Vue I18n, Tailwind, Reka Combobox и прямые адаптеры Chart.js. React/JSX/Zustand в runtime отсутствуют.
- Все основные экраны: вход, pilots, обе вкладки профиля, тренировки и detail, Comments/AI review, PDF, аналитика, настройки, совместимость, Admin/Forbidden и redirects.
- Совместимый `session-store` v0, подтверждение прав через `/auth/me`, refresh single-flight и Web Locks, generation guards, очистка кеша/черновиков и синхронизация logout между вкладками.
- 119 исходных файлов повторно проверены по SHA-256: изменений относительно baseline нет. В пяти перенесённых E2E изменены только окончания строк CRLF → LF; assertions сохранены.
- Чистая установка из lockfile, lint, format check, typecheck, сборки `55nord`/`firefly`; **63 unit/component tests** в 11 файлах прошли. Текущая Linux-копия имеет те же байты src/public/tests, что рабочий репозиторий.
- **51 E2E прошли на каждом бренде**; **56 сценариев прошли в Firefox и WebKit**. Логи: [55nord](evidence/m9/55nord-e2e.log), [Firefly](evidence/m9/firefly-e2e.log), [другие браузеры](evidence/m9/browsers-final.log).
- **330 visual scenarios** прошли: 272 сценария основных экранов, 24 снимка login/Admin/Forbidden, два сценария chart edges и 32 состояния авторизации. Сохранены 166 пар React/Vue с размерами и численными различиями для одинаковых размеров. Ширины — 390/768/1024/1440 px, основные loaded экраны также на 1920 px. Это не автоматическое утверждение полной пиксельной идентичности.
- Пройдены **5 реальных API-сценариев** на отдельном Python backend: защищённое фото/Blob/logout, login, профиль/детали, PDF Blob, Settings CRUD, Compatibility, единственный refresh при восстановлении двух вкладок и rollback. Лог — [real-backend-final-e2e.log](evidence/m9/real-backend-final-e2e.log).
- Проверен локальный атомарный откат: открытая Vue-вкладка загружает прежние lazy assets после переключения, React читает обновлённую Vue-сессию. Реальный print dialog и production cutover этим не подтверждаются.
- Проверены 20 переходов между chart routes: tooltip удаляются, ResizeObserver не сохраняют отсоединённые DOM nodes. Component test отдельно проверяет destroy Chart.js и изоляцию данных от Vue/query cache.
- Проверены смена pilotId/сброс выбранной компетенции, неполный профиль, legacy snapshot, main threshold после Settings, ID фильтров тренировок и двусторонний horizontal scroll. Delayed search и 403/422/500 Settings не возвращают устаревшие данные и не теряют draft.
- В отдельном headed Chrome проверены настоящее скрытие вкладки и resize в фоне на Analytics/Profile: шесть canvas восстановили точные пиксели, исключений нет. Использован direct CDP без эмуляции visibility/focus; [результаты](evidence/m9/native-tabs/results.json).
- Настоящий browser zoom 200% проверен в headed Chrome на восьми основных экранах: 64 активных controls доступны после scroll/focus, горизонтального overflow и exceptions нет. DPR вырос 1→2, ширина 1440→720, pinch scale остался 1. [Результаты](evidence/m9/native-zoom/results.json).
- Настоящий Chrome confirm проверен native Escape: правильный текст, возврат фокуса к Delete, отсутствие mutation и сохранение записи. Тест создаёт и убирает отдельный synthetic type. [Результат](evidence/m9/native-confirm/results.json).
- Все **95 строк матрицы** связаны с evidence: **89 пройдено, 4 частично, 2 ожидают**. Точные ограничения — в [acceptance-results.json](acceptance-results.json).

## Измерения

Пять чередующихся прогонов на одном устройстве, отдельные browser contexts, одинаковые fixtures и способ gzip. Полная методика и samples — в [performance.json](evidence/m9/performance.json).

| Сценарий | React | Vue |
| --- | ---: | ---: |
| JS для pilots, gzip | 266 885 байт | 90 911 байт |
| JS для analytics, gzip | 266 885 байт | 188 946 байт |
| Медиана готовности pilots в браузере | 371 мс | 341 мс |
| Медиана готовности analytics в браузере | 416 мс | 400 мс |
| API requests: pilots / analytics | 3 / 8 | 3 / 8 |

Время отмечается внутри страницы через MutationObserver и два animation frames после появления строк/четырёх canvas. Ожидание `page.goto` события `load` и polling Playwright не входят в эту метрику; внешнее ожидание сохранено как `harnessReadyMs`. Это локальные измерения без network throttling; не production RUM и не измерение завершения всей анимации/загрузки шрифтов. Vue pilots не загружает chart/analytics chunk заранее. Предложенный в плане предел +10% по медиане готовности здесь соблюдён.

Предыдущая методика считала также ожидание `load` и polling: после добавления статического loading она дала 460/614 мс для pilots и 487/616 мс для analytics (React/Vue). Внутренняя отметка показала, что Vue содержимое уже готово до `load`; поэтому методика уточнена симметрично для обоих приложений. Исходные результаты сохранены как `performance-polling-final.json` и `performance-polling-bootstrap.json`; время полной загрузки также записано в новых samples.

## Решения и исправления

- `PilotsPagination` объединён с `ResultsPagination`; fallback встроен в `ErrorBoundary`. Native buttons, selects, date/decimal inputs сохранены; отдельный AppButton не вводится ради обёртки над прежними controls.
- Delete использует существующий native confirm, как допускает план; cancel не выполняет DELETE.
- Settings write actions требуют `pilots:write`; читатели получают read-only controls.
- Compatibility скрывает результат неполного выбора. Accessible name поля Training type отделён от подсказки; поле даты больше не сжимается до обрезания года на 1024 px.
- Монтирование после `router.isReady()` устраняет пустой initial lazy route после входа. До завершения `/me` статический экран загрузки в `index.html` предотвращает пустую страницу; regression test воспроизвёл дефект на предыдущем artifact и прошёл на обоих брендах после исправления.
- Analytics controls переносятся по доступной ширине карточки: устранено унаследованное перекрытие подписей/полей на 1024 px. Ряды chart cards сохранены.
- Legacy crew подписан как legacy даже при отсутствующем `latestSwap`.
- Отсутствующая оценка radar сохраняется как `null`; настоящий ноль остаётся нулём. Закрытие окна подготовки PDF отменяет последующую печать.
- Media key включает user/airline/path; reconnect сбрасывает удалённый training type. Оба случая проверены в браузерах.
- Скрипт [release.py](../deploy/release.py) устанавливает проверенные байты, сохраняет старые hashed assets и атомарно меняет `current`; backend не изменяется.
- Локальная среда WSL использует игнорируемый symlink на dependencies в `/home/kolya/.cache/55north-commander-migration`. Обычный checkout устанавливается через `npm ci`; этот путь не является требованием проекта.

Подробный список решений и исправлений — [DECISIONS_AND_FIXES.md](DECISIONS_AND_FIXES.md). Исходный React repo и пользовательский Git index сохранены.

## Остаётся

- Popup blocking, реальная печать/закрытие print dialog и пользовательский pilot. Hidden-tab, browser zoom и Escape/focus return native confirm проверены в графическом Chrome; системный print dialog этим не подтверждается.
- Указать целевой domain/server/API для M10, настроить remote CI/deploy, проверить monitoring delivery с целевым DSN, выполнить cutover и наблюдение. Git remote и production destination пока не заданы.

Исторические диагностические прогоны могут содержать failures: например, `all-e2e.log` запускал fixtures против живого API, а ранние edge tests использовали неверные selectors/ожидания. Диагностический `final-harness-checks.log` также содержит ошибку запуска обычного `tsc` на Vue SFC; правильный `vue-tsc` выполнен отдельно в `harness-typecheck.log`. Актуальные полные результаты — `55nord-e2e.log`, `firefly-e2e.log`, `browsers-final.log`, `real-backend-final-e2e.log`; дополнительная проверка брендов и rollback — `brand-rollback-e2e.log`. Результаты не подменяются наличием тестовых файлов.
