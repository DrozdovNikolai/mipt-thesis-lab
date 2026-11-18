# Отчёты измерений — 14 сентября 2026

Выполнен контракт экспорта SPEC 17.3: benchmark сохраняет таблицы событий,
исходные per-sample гипотезы и S/D/I, CSV времени, Markdown/HTML и PNG/SVG
для доступных измерений. Метаданные в CSV защищены от formula injection;
HTML экранирует входной текст. Отсутствие измерений не заменяется нулём.

`event-metrics.csv` разделяет правила и обучаемый классификатор, эталонный
текст, baseline ASR и candidate ASR. Precision/recall/F1, support и TN/FP/FN/TP
сохраняются по каждой метке. Значимость — отдельная задача. Эти таблицы не
утверждают качество temporal event detection.

Дополнительные интервалы baseline/candidate WER получены из **тех же**
кластерных bootstrap-выборок. Последовательность seed, число resamples,
формула paired delta и пороги ACCEPTANCE не менялись. Для gate по-прежнему
используется CI разности candidate − baseline. Если интервала нет, отчёт
не подставляет вместо него CI другой величины.

График качество/время использует один primary cohort для обеих осей;
WER по language/condition явно обозначен как соответствующий stratum.
При missing annotations или integrity errors графики качества не строятся.
`figures.json` содержит статус и численные данные каждого графика.

Реальный доступный результат: [HTML](../reports/reporting-v1/dev-runtime/report.html),
[времена](../reports/reporting-v1/dev-runtime/runtime-trials.csv),
[PNG](../reports/reporting-v1/dev-runtime/figures/dev-runtime.png).
Это 64 ранее выполненных dev-прогона, small/int8 CPU. Старые inference-хеши
сохранены отдельно от хеша нового renderer. ASR при визуализации не запускался;
gold/test не открывались. Единственный измеренный график — скорость.
WER/F1 и доказательство улучшения остаются `NEEDS_MORE_DATA`.

Проверено 228 тестов, включая 9 integration; отдельно 4 CPU и 4 GPU реальных
offline-прогона актуального кода, без cache hit. Ruff, mypy и проверка зависимостей
прошли. HTML и PNG просмотрены. Отчёт проверки:
[verification.json](../reports/reporting-v1/verification.json).
Предыдущие проверки отказоустойчивости не выдаются за новый прогон:
использовано их сохранённое свидетельство с проверкой неизменности jobs/db/api/core
и версий зависимостей. Исходные SPEC/ACCEPTANCE/SOURCES сохранены.

Baseline заново зафиксирован в `/artifacts/reporting-v1/baseline.lock.json`;
копия — `reports/reporting-v1/baseline.lock.json`. Параметры и веса прежние.
Старая заморозка не перезаписывалась. Перед final test всё ещё требуются
человеческие эталоны, scored dev selection и её новая заморозка.

Команды действительно выполнены из PowerShell; аргументы исполняются в
Linux-контейнере. Эти команды без переменных shell одинаковы для PowerShell/Linux:

```sh
docker build --target base -t north55-speech:0.1.0 .
docker compose --profile tools run --rm --entrypoint python tools -m pytest tests -q --junitxml=/reports/reporting-v1/all-tests.xml
docker compose --profile tools run --rm --entrypoint python tools -m scripts.render_pending_dev_report
docker compose --profile tools run --rm tools benchmark freeze-baseline --output /artifacts/reporting-v1/baseline.lock.json
```

Повторная команда с тем же кодом и конфигурацией возвращает прежнюю заморозку;
перезапись отличающейся заморозки запрещена. Для нового эксперимента выберите
новую версию. Воспроизведение графика использует сохранённые
`pending-dev-ablation.json` и `pending-dev-ablation-plan.json` в reports volume.
Это не новый benchmark и не разрешение использовать test при настройке.

Для повторного запуска самого render-скрипта после локальных правок scripts,
PowerShell (этот вариант также исполнен):

```powershell
docker compose --profile tools run --rm --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" tools -m scripts.render_pending_dev_report
```

Linux host syntax для того же bind mount:

```sh
docker compose --profile tools run --rm --entrypoint python -v "$PWD/scripts:/app/scripts:ro" tools -m scripts.render_pending_dev_report
```

Чтобы использовать уже установленные GPU/train зависимости, выполнены:

```sh
docker build -f scripts/Dockerfile.update-runtime --build-arg BASE_IMAGE=north55-speech-gpu:gate-hardening-v1 --build-arg RUNTIME_EXTRA=gpu -t north55-speech-gpu:0.1.0 .
docker build -f scripts/Dockerfile.update-runtime --build-arg BASE_IMAGE=north55-speech-train:gate-hardening-v1 --build-arg RUNTIME_EXTRA=train -t north55-speech-train:0.1.0 .
```

Эти команды требуют сохранённых исходных images. На новой машине используйте
основные Dockerfile GPU/train из README; большие зависимости будут скачаны.
Matplotlib 3.11.2 закреплён как обязательная зависимость отчётов; ранее он уже
присутствовал в lock для optional окружения. Версии других пакетов не изменились.

Данные повторно прикладывать не нужно. Для продолжения обучения нужен человек,
который проверит [пакет разметки](review_packet.md). Пакет позволяет начать
train/dev, но не закрывает требование минимум 20 независимых test-групп.
