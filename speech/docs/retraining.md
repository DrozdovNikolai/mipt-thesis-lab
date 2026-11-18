# Переобучение на имеющихся данных

Результаты текущего запуска: [`reports/retraining-v1/report.md`](../reports/retraining-v1/report.md).
Точный протокол зафиксирован до обучения в [`protocol.md`](../reports/retraining-v1/protocol.md).

Это две новые исследовательские версии Whisper-small: на прежних 33 кабинных
парах и на тех же парах с добавлением 400 EN/RU записей. Обе — по 120 optimizer
steps, с одним заранее выбранным checkpoint-120. Исходный Whisper остаётся
главным baseline. В этом сравнении checkpoint меняется, precision сохраняется.
Автоматической замены модели приложения нет.

## Что уже есть на этой машине

- `data/curated/retraining-v1/control/train.jsonl`: 33 слабые пары.
- `data/curated/retraining-v1/augmented/train.jsonl`: 433 пары.
- `data/curated/retraining-v1/dev.jsonl`: неизменённые 35 слабых dev-пар.
- `north55-speech_audio_data`: исходное/подготовленное аудио, доступно контейнерам в `/audio`.
- `north55-speech_model_cache`: исходные Transformers/CT2 веса и новые модели.
- `reports/retraining-v1`: планы, хеши, training manifests, сырые прогнозы,
  edit counts, итоговые метрики, проверки и Docker-логи. Большие сырые файлы
  остаются локально и исключены из Git; это не удаление измерений.

Новые веса в model volume:

```text
/models/whisper-small-retraining-v1-control/adapter
/models/whisper-small-retraining-v1-control/merged
/models/whisper-small-retraining-v1-control/checkpoints/checkpoint-120
/models/whisper-small-retraining-v1-control-ct2
/models/whisper-small-retraining-v1-augmented/adapter
/models/whisper-small-retraining-v1-augmented/merged
/models/whisper-small-retraining-v1-augmented/checkpoints/checkpoint-120
/models/whisper-small-retraining-v1-augmented-ct2
```

`training_coverage.sample_load_counts` показывает загрузку каждого примера;
`global_optimizer_steps` — реальные шаги. Число проходов по данным различается:
фиксируется одинаковый бюджет шагов, а не эпох. Поле `label_source` называет
семейство политики; фактический состав каждой модели находится в
`reference_status_counts` (у control только `weak`).

## Проверить сохранённый результат

PowerShell, из корня репозитория:

```powershell
python scripts/report_retraining.py
./scripts/run_retraining.ps1 infer -Selected augmented -Resume
python scripts/report_retraining.py
```

Linux/WSL, из корня репозитория:

```sh
python3 scripts/report_retraining.py
sh scripts/run_retraining.sh infer --selected augmented --resume
python3 scripts/report_retraining.py
```

Повторный inference использует сохранённые 661 результата только при совпадении
плана, настроек и исходной идентичности запроса. Сохраняется отдельная запись
попытки; она должна показать `resumed_records=661`, `new_records=0`. Это проверка
повторного запуска завершённого задания, не имитация аварии во время обучения.

## Последовательность полного воспроизведения

Команды ниже уже использованы для этого запуска. На существующих выходных
директориях `freeze`, `train` и `freeze-eval` намеренно отказываются перезаписывать
историю. Полный повтор требует отдельного окружения с теми же исходными
данными/весами и без результатов `retraining-v1`. Не удаляйте рабочие volumes.

Предусловия: Docker с NVIDIA runtime, ровно одна поддерживаемая GPU, базовые
образы `north55-speech-gpu:0.1.0`, `north55-speech-train:publisher-v2`; данные из
`docs/quality_pairs.md` и предыдущие frozen diagnostic inputs/references из
`language-large-v1`. Идентификаторы реально использованных Docker-образов
сохраняются в `north55-retraining-v1-*.json`, зависимости — в frozen `uv.lock`.
Запуск использовал RTX 5070 Ti (GPU 0), CUDA_VISIBLE_DEVICES=0. Тренировочный
код не применяет неявный DataParallel ко второй установленной карте.

PowerShell:

```powershell
./scripts/run_retraining.ps1 tests
./scripts/run_retraining.ps1 freeze
./scripts/run_retraining.ps1 prepare
./scripts/run_retraining.ps1 train -Selected control
./scripts/run_retraining.ps1 train -Selected augmented
./scripts/run_retraining.ps1 freeze-eval
./scripts/run_retraining.ps1 infer -Selected parent
./scripts/run_retraining.ps1 infer -Selected control
./scripts/run_retraining.ps1 infer -Selected augmented
./scripts/run_retraining.ps1 score
./scripts/run_retraining.ps1 cpu
python scripts/report_retraining.py
```

Linux:

```sh
sh scripts/run_retraining.sh tests
sh scripts/run_retraining.sh freeze
sh scripts/run_retraining.sh prepare
sh scripts/run_retraining.sh train --selected control
sh scripts/run_retraining.sh train --selected augmented
sh scripts/run_retraining.sh freeze-eval
sh scripts/run_retraining.sh infer --selected parent
sh scripts/run_retraining.sh infer --selected control
sh scripts/run_retraining.sh infer --selected augmented
sh scripts/run_retraining.sh score
sh scripts/run_retraining.sh cpu
python3 scripts/report_retraining.py
```

Оба wrapper вызывают один `run_retraining.py`; фактически контейнер выполняет
`python -u -m scripts.retrain_asr ...` из снимка `frozen/`. Все этапы выполняются
с `--network none`; веса уже получены. Для inference смонтированы только
референс-свободные входы и выход выбранной системы. Тексты ответов доступны
отдельному scorer; train видит только train и разрешённый dev.

Inference-системы этого запуска частично выполнялись одновременно. Время и
device-wide memory сохранены как наблюдения при совместной нагрузке, без
утверждения об изолированной сравнительной производительности.
`execution-scheduling.json` фиксирует это решение; параметры точности не менялись.

Контейнер пишет закрытые артефакты от UID 10001. Если другой Linux/WSL UID
не может прочитать их, `report_retraining.py` автоматически считает отчёт
в offline-контейнере от того же владельца. Launcher аналогично создаёт
недостающую выходную папку через владельца контейнера; права существующих
файлов не расширяются. На отдельном Linux-хосте bind-каталоги исследования
и данных должны разрешать запись UID 10001; проверенное здесь окружение —
Windows Docker Desktop и Ubuntu WSL с этими же volumes.

Обучение с самого начала воспроизводит фиксированный рецепт, но CUDA не даёт
обещания побитово одинаковых результатов между разным железом/runtime. Хеши
позволяют проверить именно сохранённый выполненный запуск.

## Как трактовать результат

`implemented` означает наличие рабочего кода; `executed` — состоявшееся обучение
и распознавание; `verified` — проверенные артефакты/инварианты, не автоматический
PASS качества. Программные тесты используют искусственные метаданные и не
считаются независимыми речевыми эталонами.

Для кабинного gate нужны независимые данные и проверенные критические сущности
в объёме ACCEPTANCE.yaml. Готовые общие EN/RU тексты позволяют обучать ASR, но
не дают человеческих event labels, значимости, temporal intervals или
доказанного качества mixed. Результаты на уже известных dev/control наборах
публикуются как диагностика. Слабые издательские привязки остаются слабыми.
