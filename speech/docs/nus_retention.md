# Проверка удержания исходных навыков Whisper

Эксперимент `nus-retention-v1` сравнивает два новых адаптера на той же смеси
675 train-пар: обычное обучение и обучение с KL-штрафом относительно исходного
Whisper. Готовые расшифровки сохранены. Учитель предоставляет распределения
токенов для штрафа; они не используются как человеческая разметка или test-эталон.
Обоснование метода — [Learning without Forgetting](https://arxiv.org/abs/1606.09282);
пользу именно здесь устанавливает собственное сравнение, а не ссылка на статью.

Оба адаптера стартуют одинаково, получают один порядок train-примеров и выполняют
по 1200 реальных AdamW updates. Arm 1 — CE, arm 2 — CE+KL с весом 1 и T=2.
Кандидат arm 2 задан до запуска. Сеть, base weights и encoder заморожены;
train работает в BF16, итоговый faster-whisper у обеих моделей — CUDA float16.
Это сравнение обучения с одинаковой архитектурой, а не улучшение preprocessing
на одном неизменном checkpoint. Старый baseline и его decoding policy сохранены.

## Предпосылки

Нужны Docker с GPU BF16 (здесь RTX 5070 Ti), image
`north55-speech-train:publisher-v2`, исходные volumes `north55-speech_model_cache`
и `north55-speech_audio_data`. Веса уже получены. Данные остаются под ограничениями
источников и существующим пользовательским разрешением на исследование NUS.
Исходные volumes доступны только для чтения, сеть контейнеров выключена.
Результат записывается в новый `north55-speech_nus_retention_v1`.

Локально необходимы `data/curated/nus-training-v1/train.jsonl`, permission/plan/training
из `reports/nus-training-v1` и inputs/scoring из `reports/nus-lora-ablation-v1`.
Массовые аудио, тексты, predictions и веса не входят в Git: одного клона недостаточно
для повторения исторического опыта. Это явно ограничение воспроизводимости пакета.

## PowerShell, из корня Speech

```powershell
python -m scripts.run_nus_retention freeze
python -m scripts.run_nus_retention init
python -m scripts.run_nus_retention tests
python -m scripts.run_nus_retention train
python -m scripts.run_nus_retention convert
python -m scripts.run_nus_retention fit 1
python -m scripts.run_nus_retention fit 2
python -m scripts.run_nus_retention transfer 1
python -m scripts.run_nus_retention transfer 2
python -m scripts.run_nus_retention cpu 1
python -m scripts.run_nus_retention cpu 2
python -m scripts.run_nus_retention score-transfer
```

`1` и `2` — номера arms, не число training steps. Сохранённый `step` в старом
ASR-контракте также содержит номер arm; `actual_updates` в training/manifest
содержит реальное число обновлений. На каждую модель: 275 NUS fit и 159 controls,
плюс EN/RU CPU smoke. Всего 868 GPU и 4 CPU ASR, без автоматического расширения.

Команды freeze/init/train/convert/score отклоняют перезапись существующей версии.
Сбой обучения сохраняется; бесшумного перезапуска или превышения бюджета нет.
Ручной train loop не поддерживает возобновление незавершённого arm с середины;
optimizer/RNG сохраняются после полного arm для аудита. Старый pipeline recovery
и очередь сервиса этим экспериментом не меняются.
Повтор inference проверяет identities и возобновляет сохранённые успешные ответы,
записывая новый replay audit. Сбой ASR нельзя автоматически заменить удачным ответом.
Train не монтирует dev/test-эталоны, inference не монтирует никакие эталоны;
тексты доступны только отдельному scorer после распознавания.

Проверки совместимости:

```powershell
docker run --rm --network none -e PYTHONPATH=/app:/app/src -v C:/DEV/MIPT/Diploma/Speech/reports/nus-retention-v1/frozen:/app:ro -v C:/DEV/MIPT/Diploma/Speech/reports/nus-retention-v1/tests:/results --entrypoint python north55-speech-train:publisher-v2 -m pytest -q -p no:cacheprovider tests/test_nus_training.py tests/test_convergence.py tests/test_continuation.py tests/test_decoder_adaptation.py --junitxml=/results/backcompat.xml
```

## Linux / WSL

Все команды launcher используют стандартную библиотеку Python и работают с
`python3` вместо `python`. На текущем хосте:

```bash
cd /mnt/c/DEV/MIPT/Diploma/Speech
python3 -m scripts.run_nus_retention fit 2
```

Это replay существующих ответов, а не повтор обучения. Для отдельного scorer
нужна новая папка `reports/nus-retention-v1/linux-replay`, содержащая копии
`plan.json`, `inputs.json`, `scoring`, `fit-1`, `fit-2`, `transfer-1`, `transfer-2`,
но не готовые `comparison.json` и `scored-counts.json`.

```bash
docker run --name north55-nus-retention-score-linux-v1 --network none -e PYTHONPATH=/app:/app/src -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-retention-v1/frozen:/app:ro -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-retention-v1/linux-replay:/study -v north55-speech_audio_data:/audio:ro --entrypoint python north55-speech-train:publisher-v2 -m scripts.nus_retention score-transfer
```

Сравните побайтно `comparison.json`, `scored-counts.json`,
`legacy-waveform-evidence.json`; проверка сохраняется в `cross-platform-replay.json`.

## Проверка отчёта

После измерений и Linux replay отдельный presentation script проверяет артефакты,
сохранённые optimizer states и пересчитывает агрегаты из per-sample counts:

```powershell
$repoPath=(Get-Location).Path
docker run --name north55-nus-retention-report-v1 --network none -e PYTHONPATH=/app:/app/src -v "${repoPath}/reports/nus-retention-v1/frozen:/app:ro" -v "${repoPath}/scripts/report_nus_retention.py:/presentation/report.py:ro" -v "${repoPath}/reports/nus-retention-v1:/report" -v north55-speech_nus_retention_v1:/experiment:ro --entrypoint python north55-speech-train:publisher-v2 /presentation/report.py
```

Рабочий код может иметь более позднее форматирование импортов; запуск использует
неизменённую frozen-копию и проверяет её хеши. Presentation script хранит собственный
хеш и не участвует в обучении, выборе модели или scoring.

В `integrity-rejection.json` сохранена исполненная проверка отказа: гипотеза
первого ответа изменена только в отдельной копии, scorer отклонил её с
`Prediction changed` до расчёта метрик. Исходный hash подтверждён повторно;
новых ASR-вызовов эта проверка не делает. Команда и ожидаемый exit code записаны
в audit, копия с текстами и log остаётся локальной и исключена из Git.

## Ограничение выводов

NUS-fit оценивает усвоение train. Пять человеческих dev-клипов, 115 слов, три уже
многократно просмотренные группы не заменяют независимый test. Общий RU — одна
консервативная группа, его bootstrap не даёт популяционного доверительного интервала.
Новые human entity/event/temporal labels этим опытом не появляются. RU/mixed cockpit
качество остаётся неподтверждённым. Пороги и исчерпанный бюджет release-search сохранены.
Ни один адаптер нельзя подключать в release по результатам этого diagnostic опыта.

[Протокол](../reports/nus-retention-v1/protocol.md) ·
[Отчёт](../reports/nus-retention-v1/report.md) ·
[Измерения](../reports/nus-retention-v1/comparison.json)
