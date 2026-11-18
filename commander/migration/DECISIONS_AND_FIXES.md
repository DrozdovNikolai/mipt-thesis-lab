# Решения и исправления при переносе

Рабочий scope задан [MIGRATION_PLAN.md](../MIGRATION_PLAN.md), пофайловые исключения — [source-inventory.json](source-inventory.json). Решения ниже относятся к реализованному Vue frontend; production rollout ещё не выполнен.

## Решения

- Оба бренда сохранены; локальный release по умолчанию — 55nord. Существующая AI review panel переносится из detail DTO, новый AI endpoint не используется.
- Native buttons, select/date/decimal inputs сохраняют поведение и CSS. Отдельный `AppButton` без дополнительного поведения не вводится. `ResultsPagination` заменяет дублирующиеся pagination-компоненты; error fallback входит в `ErrorBoundary`.
- Reka Combobox используется для remote autocomplete; native confirm — для удаления, как допускает план. Подтверждение отмены и keyboard Escape/Tab проверяются отдельно.
- Состояние сессии совместимо с React `session-store` version 0. Web Locks координирует refresh на HTTPS/localhost; в браузерах без Web Locks сохраняется single-flight внутри вкладки.
- Analytics state/queries остаются внутри `AnalyticsView` рядом с chart composition; pure calculations вынесены отдельно. Дополнительные composables без повторного использования не вводятся. Четыре server query families и локальные фильтры разделены по поведению.
- Поддержка проверена на Chromium 145, Firefox 146, WebKit 26 в Linux Playwright. Это не утверждение о ручной проверке Safari/macOS или других корпоративных browser versions.
- Изолированный Python API использует синтетическую БД. Он подтверждает контракт текущего backend; адрес и версия целевого staging/production ещё не заданы.

## Исправленные проблемы

| Проблема | Результат | Проверка |
| --- | --- | --- |
| Ошибки login смешивались с bootstrap; повторная отправка во время ожидания | Отдельная ошибка формы, disabled pending, retry сохраняет URL | `session-routes.spec.ts`, `acceptance-edges.spec.ts` |
| Поздний refresh, `/me` или mutation после logout мог вернуть старое состояние | Generation guards, завершение сессии и очистка кеша | `http-client.test.ts`, `session-persistence.test.ts`, real API two-tab test |
| Lazy initial route мог оставить пустую страницу; ожидание `/me` до mount также оставляло пустой экран | Mount после `router.isReady()` и статический loading до завершения bootstrap | Все route E2E; `bootstrap-before-fix.log` воспроизводит дефект старого artifact, `55nord-e2e.log` / `firefly-e2e.log` подтверждают исправление |
| React оставался на loading после `/me` 503, при login 401 показывал лишь unauthorized | Vue показывает ошибку login и retry/logout при ошибке проверки сессии | `session-routes.spec.ts`, 32 auth visual cases |
| Analytics labels пересекали поля в узких desktop cards | Controls переносятся по ширине карточки | `analytics-layout.spec.ts`, `resources-accessibility.spec.ts`, снимки 1024 px |
| Поле даты Compatibility сжималось на 1024 px | Блок date/actions не сжимается, год и picker видны полностью | `final-visual.log`, `VISUAL_REVIEW.md` |
| Отсутствующая radar grade превращалась в 0 | `null` сохраняется, настоящий 0 отображается | `profile-charts.test.ts` |
| Legacy crew без `latestSwap` получал неоднозначную подпись | Отдельный legacy fallback; absent/null различаются | `adverse-states.spec.ts` |
| Закрытое пользователем окно подготовки PDF могло вызвать позднюю печать | Закрытие отменяет дальнейший print flow, освобождает ресурсы | `report-printing.test.ts` |
| В ключе media cache не было airline scope | User + airline + path; старый Blob освобождается | `acceptance-edges.spec.ts`, `media-lifecycle.test.ts`, real media smoke |
| Удалённый выбранный training type оставался в сравнении после refetch | Сбрасывается выбранный тип и старый результат | `settings-compatibility.spec.ts`, reconnect case |
| Nginx regex static location перебивал immutable asset cache | `/assets/` использует `^~`; старые chunks сохраняются при rollout | `rollback.spec.ts`, real Nginx smoke |

Матрица отдельно перечисляет частично проверенные сценарии. Наличие тестового файла или screenshot не закрывает ручную печать, zoom, весь набор visual differences и пользовательский pilot.
