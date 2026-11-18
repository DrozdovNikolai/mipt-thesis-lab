# NUS: проверка повторов, fitting и абляция адаптера

Результат текущей работы находится в
[reports/nus-diagnosis-v1/report.md](../reports/nus-diagnosis-v1/report.md).
Эта диагностика не меняет рабочую модель и не добавляет обучение.

## Среда

Запускать из корня репозитория. Нужны Python 3, Docker, существующий локальный
image `north55-speech-train:publisher-v2` и volumes `north55-speech_audio_data`,
`north55-speech_model_cache`. GPU-инференс требует NVIDIA Container Runtime.
Драйверы сами запускают контейнеры с `--network none`; данные, модели и source
монтируются только для чтения, кроме новых model versions на стадии merge.
Inference не получает директорию scoring с текстами или историческими ответами.

Исходные данные NUS и их разрешение остаются прежними; нет новой публичной
лицензии или права распространения. Команды ничего не скачивают.

## PowerShell / Linux

В PowerShell используйте `python`; в Linux допустимо заменить его на `python3`.

Первичный запуск диагностики (freeze одноразовый, существующие планы сохраняются):

```sh
python scripts/run_nus_failure_diagnosis.py freeze
python scripts/run_nus_failure_diagnosis.py tests
python scripts/run_nus_failure_diagnosis.py trace parent_on
python scripts/run_nus_failure_diagnosis.py trace parent_off
python scripts/run_nus_failure_diagnosis.py trace nus_on
python scripts/run_nus_failure_diagnosis.py trace nus_off
python scripts/run_nus_failure_diagnosis.py fit parent_on
python scripts/run_nus_failure_diagnosis.py fit nus_on
python scripts/run_nus_failure_diagnosis.py context parent_off
python scripts/run_nus_failure_diagnosis.py context nus_off
python scripts/run_nus_failure_diagnosis.py cpu parent_on
python scripts/run_nus_failure_diagnosis.py cpu parent_off
python scripts/run_nus_failure_diagnosis.py cpu nus_on
python scripts/run_nus_failure_diagnosis.py cpu nus_off
```

Context expansion следует frozen протоколу: здесь запущен, поскольку у части
trace-примеров текст изменился. Состав всех 675 контролей сохраняется.
Повтор inference переиспользует только совпадающие успешные records; несовпадение
или существующая ошибка прерывает запуск. Ошибки нельзя перезаписывать молча.

Абляция на сохранённых весах, без обучения:

```sh
python -m scripts.run_nus_lora_ablation freeze
python -m scripts.run_nus_lora_ablation tests
python -m scripts.run_nus_lora_ablation merge
python -m scripts.run_nus_lora_ablation control encoder
python -m scripts.run_nus_lora_ablation fit encoder
python -m scripts.run_nus_lora_ablation cpu encoder
python -m scripts.run_nus_lora_ablation control decoder
python -m scripts.run_nus_lora_ablation fit decoder
python -m scripts.run_nus_lora_ablation cpu decoder
```

После обоих прогонов, перед scoring, один раз подготовить совместимость с
историческими parent-ответами без runtime PCM hash. Замороженные исходники
сохраняются, исправленные scorer-копии и их hashes идут в `scoring-repair/`:

```sh
python -m scripts.prepare_nus_scoring_repair
python scripts/run_nus_failure_diagnosis.py score
python -m scripts.run_nus_lora_ablation score
```

На уже подготовленных текущих отчётах повторяют только две последние команды.
Саму поправку повторно создавать нельзя. Она проверяет file hash, путь,
длительность, язык и zero-gain preparation исторической записи, затем
сопоставляет восстановленный PCM с новым runtime hash. Неизвестное усиление
или преобразование без PCM evidence отклоняется. Метрики и пороги не меняются.
Первые ошибки missing field/import path сохранены в отдельных контейнерах;
scorer использует `PYTHONPATH=/app:/app/src`. Новых ASR-вызовов для исправления нет.

Дополнительно исполнено из WSL Ubuntu:

```sh
python3 scripts/run_nus_failure_diagnosis.py trace nus_on
python3 -m scripts.run_nus_lora_ablation fit encoder
python3 scripts/run_nus_failure_diagnosis.py score
python3 -m scripts.run_nus_lora_ablation score
```

Первые две команды переиспользовали 10 и 275 записей, новых ASR-вызовов не было.
Оба comparison.json и legacy-waveform-evidence.json совпали побайтно с
PowerShell. Контрольные суммы до/после сохранены в
`reports/nus-diagnosis-v1/cross-platform-replay.json`.

`merge` проверяет исходную базу и адаптер, клонирует A/B tensors, зануляет только
B отключаемой части и сохраняет две новые model versions. Повторный merge в те
же каталоги запрещён. Дополнительных коэффициентов смешивания/обучения нет.
Checkpoint изменяется; это отдельное сравнение весов, а не same-checkpoint gain.

Сохранённые пути в model volume:

```text
/models/whisper-small-nus-encoder-v1/adapter
/models/whisper-small-nus-encoder-v1/merged
/models/whisper-small-nus-encoder-v1-ct2
/models/whisper-small-nus-decoder-v1/adapter
/models/whisper-small-nus-decoder-v1/merged
/models/whisper-small-nus-decoder-v1-ct2
```

Сводный отчёт после обоих scoring, fit-audit и сохранения application-runtime:

```sh
python scripts/report_nus_diagnosis.py
```

Статусы implemented/executed/verified относятся к конкретным операциям.
Успешные контейнеры, tests или training-set WER не являются quality gate PASS.
Human эталоны, их ревизии и original audio никогда не исправляются по ASR.

## Отдельный постфактум-аудит train-пар

`scripts/audit_nus_fit_cases.py` проверяет все сохранённые ответы, считает
secondary canonical WER, измеряет PCM и VAD на исходном аудио. Для этого worker
нужны mounts `/study` (весь nus-diagnosis-v1, read-only), `/output` (fit-audit),
`/audio` (read-only), актуальная scripts/ и frozen src/. Аудио и слова не меняются.
Первый запуск с единственным script mount остановился до обработки из-за
отсутствующего helper-модуля. Повтор с scripts/ выполнен отдельно; первичный
контейнер `north55-nus-fit-audit-v1` и успешный `north55-nus-fit-audit-v2` сохранены.
Это ошибка окружения аудитора, не ASR-ответ и не исключённый пример.

Прямые сырые ответы/тексты остаются локальными под `.gitignore`; frozen код,
агрегированные метрики, планы и контрольные суммы сохраняются в репозитории.
