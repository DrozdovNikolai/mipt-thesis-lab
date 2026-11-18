# Локальное распознавание авиационного радиообмена

Отдельный профиль English ATC. Его рецепт создаётся только после прохождения
критериев [опыта aviation-v1](../reports/aviation-v1/protocol.md).
Измерения: [отчёт](../reports/aviation-v1/report.md).

На ATCOSIM WER исходной medium.en 62.57%, авиационной адаптации — 12.11%.
Для кабинных разговоров этот профиль не подходит: на пяти проверенных фрагментах
WER вырос с 13.91% у прежнего small до 86.09%.

Поместите WAV/FLAC/MP3 в `data/local-audio/` и выполните из корня проекта:

```powershell
docker compose -f compose.aviation-local.yaml run --rm transcribe --input /input/radio.wav
```

Для первого запуска уже подготовлен пример из набора:

```powershell
docker compose -f compose.aviation-local.yaml run --rm transcribe --input /input/aviation-demo-sm2.wav
```

Язык English задан профилем. `ru`, `mixed` и `auto` отклоняются, чтобы английская
специализация не подменяла прежнюю языковую маршрутизацию. Для прежних EN/RU
профилей остаётся [compose.improved-local.yaml](../compose.improved-local.yaml).

Новая папка в `reports/local-transcriptions/aviation/` содержит `transcript.txt`,
`result.json`, исходные таймкоды и сведения о модели. Сеть отключена; исходный файл
сохраняется. Нужны Docker Desktop, NVIDIA GPU и уже загруженные локальные веса.
Явный `--cpu` использует int8; измеренный результат относится к GPU/float16.
Этот Compose всё равно резервирует GPU и не является CPU-only установщиком.

Измеренная область — английская речь диспетчеров ATCOSIM в симуляции. Качество
реального VHF, русской авиационной речи и кабинных разговоров из этого результата
не следует. Черновики событий в полном JSON создаёт прежняя NLP-часть проекта;
она в данном опыте не переобучалась и для радиообмена не валидирована.

## Повторный подсчёт и продолжение вычислений

Завершённое сравнение пересчитывается без новых ASR-вызовов:

```powershell
docker compose -f compose.aviation.yaml run --rm score
```

Для продолжения незавершённой модели (последовательно на одном GPU):

```powershell
docker compose -f compose.aviation.yaml run --rm infer infer small
docker compose -f compose.aviation.yaml run --rm infer infer medium
docker compose -f compose.aviation.yaml run --rm infer infer atc
```

Завершённые ответы проверяются по хешам и не пересоздаются; завершённый execution
также не перезаписывается. Исходные данные находятся в `data/input/atcosim-v1/`,
а общие для всех моделей WAV 16 кГц — в `data/curated/aviation-v1/audio/`.
Эталонные тексты и GPU-входы хранятся отдельно.
Манифест стандартной схемы проекта: `data/curated/aviation-v1/atcosim-dev.jsonl`.
После этого исследования набор относится к локальному dev, хотя исходное зеркало
называет его test. Для следующего обучения нужен отдельный независимый контроль.
