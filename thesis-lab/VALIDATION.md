# Проверки

Проверки выполнены в candidate worktree. Backend использует отдельную
`thesis_tests`; основные бенчмарки используют `thesis_bench`.

| Компонент | Итог | Лог |
|---|---|---|
| Backend: sync, snapshot, финализация и восстановление | 20 passed | `results/backend-initial.log` |
| Backend: исходная аналитика Commander | 23 passed в общей первой проверке; 6 новых тестов тогда выявили дефект прототипа | `results/projection-tests.log` |
| Backend: новые тесты проекции после исправления, включая конкурентную запись | 7 passed | `results/projection-final.log`, XML рядом |
| Instructor: семь целевых файлов тестов | 104 passed, последовательный запуск | `results/instructor-tests-sequential.log` |
| Instructor: настоящий Chromium, IndexedDB recovery suite и общая identity | All browser integration tests passed | `results/instructor-browser-recovery-final.log` |
| Session: очередь сохранения сценария | regression harness passed | `results/session-regression.log` |
| Session: production build | passed | `results/session-build.log` |
| Commander: production build | passed; предупреждения размера chunk сохранены | `results/commander-build.log` |
| Commander: два браузерных сценария | 2 passed | `results/commander-browser-preview.log` |
| Python: ошибки категории F в новом коде | исправлены; финальная проверка без ошибок | `results/lint.log` |
| Основная серия: полнота и согласованность данных | 108 тренировок, 216 сохранений, 144 серии / 5760 HTTP-запросов, 99 сравнений | `results/main-20260916T130741Z-all/verification.json` |
| Финальное распределение после всех изменений и rebuild | Три tenant, восемь компетенций; независимый арифметический эталон пройден | `results/main-20260916T130741Z-all/final-analytics-audit.json` |

Первые неуспешные попытки сохранены. При разработке проекции устранён дефект
истечения ORM-состояния после пустого прохода обработчика. При первоначальном
параллельном запуске Flutter были два сбоя по временным ограничениям; полный
целевой набор затем прошёл с `--concurrency=1 --timeout=2m`. Браузерные запуски
потребовали отсутствовавших динамических библиотек, готовой сборки Commander
и увеличения script timeout ChromeDriver для интеграционного набора Flutter.
Это изменения стенда; исходный production-код Flutter/TypeScript не менялся.

UI-тесты Commander используют штатные моки API и не являются сквозной проверкой
новой проекции. Её HTTP-контракт, PostgreSQL и корректность проверяются
backend-тестами и основным H3 бенчмарком. Браузер Instructor использует
настоящий IndexedDB; отсутствие потерь при физическом обесточивании не проверялось.

Для повторения новых backend-тестов:

```bash
docker compose up -d --wait test-db redis
docker compose run --rm --no-deps tests pytest -q -o addopts= \
  -o cache_dir=/tmp/pytest-cache tests/test_commander_analytics_projection.py
```

Конкретный список исходных проверок виден в логах и исходниках worktree.

В Commander после `npm ci --ignore-scripts` и `npm run build`:

```bash
THESIS_CHROME=/path/to/chrome npm exec playwright test \
  --config playwright.thesis.config.ts \
  tests/e2e/analytics-layout.spec.ts tests/e2e/training-sessions-route.spec.ts
```

Для Flutter browser recovery нужен ChromeDriver совместимой версии, запущенный
на порту 14445, и Chromium с библиотеками ОС. Использован Chromium 148.0.7778.96;
происхождение ChromeDriver сохранено в `provenance/chromedriver.json`.

```bash
flutter drive --driver=test_driver/thesis_integration_test.dart \
  --target=integration_test/training_runtime_recovery_indexeddb_test.dart \
  -d web-server --web-hostname=127.0.0.1 --web-port=14278 \
  --driver-port=14445 --browser-name=chrome \
  --chrome-binary=/path/to/chrome --headless
```
