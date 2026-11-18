# Подготовка пар без новой ручной разметки

Этот этап использует только train для нового автоматического отбора. Издательские
тексты не исправляют числа или отрицания в распознавании. Принимается только полное
lexical-согласие small EN, large с автоопределением языка и найденного участка
сценария, с прежними проверками forced alignment и дополнительными проверками
таймкодов. Порог уверенности модели не является вероятностью правильности пары.

[Фактический отчёт](../reports/pair-quality-v1/report.md),
[замороженный протокол](../reports/pair-quality-v1/protocol.md),
[проверки](../reports/pair-quality-v1/verification.json).

Новые артефакты:

- `data/curated/pair-quality-v1/training/train.jsonl`: строгий автоматический BLeRIOT
  train, статус weak. Все ответы и причины отказов находятся в этом же пакете.
- `data/curated/pair-quality-v1/training/dev.jsonl`: точная копия прежних 35 dev-пар.
- `data/curated/training-support-v1/train.jsonl`: отдельные готовые EN/RU тексты
  поставщиков корпусов. Их статус human_verified означает источник разметки;
  местная ручная проверка не выполнялась, что явно отражено в provenance.
- Аудио лежит в прежнем volume `north55-speech_audio_data`, в новых каталогах
  `pair-quality-v1` и `training-support-v1`. Исходники и веса сохранены.

Секреты, аудио, сырые ответы и приобретённые архивы остаются вне Git. Для
воспроизведения старого исполнения нужны соответствующие локальные артефакты.

## PowerShell

Все команды — из корня проекта. Этапы запускаются по очереди; runner запускает
именованный контейнер и возвращается сразу. Проверяйте код завершения перед
следующим этапом. Уже существующий контейнер runner не заменяет.

```powershell
./scripts/run_quality_pairs.ps1 prepare
docker wait north55-quality-pairs-prepare-v1
./scripts/run_quality_pairs.ps1 small
docker wait north55-quality-pairs-small-v1
./scripts/run_quality_pairs.ps1 large
docker wait north55-quality-pairs-large-v1
./scripts/run_quality_pairs.ps1 assemble
docker wait north55-quality-pairs-assemble-v1
```

`prepare`, `small`, `assemble` реально запущены через PowerShell. Large запущен
через Linux runner ниже. Все inference-контейнеры используют `--network none`;
им не монтируются сценарии, прежние эталоны или test. Получение данных — отдельное
сетевое действие. Модели уже были явно получены в предыдущих этапах.

## Linux / WSL

```sh
sh scripts/run_quality_pairs.sh prepare
docker wait north55-quality-pairs-prepare-v1
sh scripts/run_quality_pairs.sh small
docker wait north55-quality-pairs-small-v1
sh scripts/run_quality_pairs.sh large
docker wait north55-quality-pairs-large-v1
sh scripts/run_quality_pairs.sh assemble
docker wait north55-quality-pairs-assemble-v1
```

Реально выполнен вызов large через WSL Ubuntu:

```powershell
wsl -d Ubuntu -- sh /mnt/c/DEV/MIPT/Diploma/Speech/scripts/run_quality_pairs.sh large
```

Для намеренного продолжения существующего запуска используется `docker start -a`
с его именем. Готовые ответы проверяются по идентичности запроса и пропускаются;
исходный driver и его хеши сохранены в `reports/pair-quality-v1/frozen`.
Изменение замороженного кода или входов останавливает продолжение.

Сборка вынесена в `scripts/assemble_quality_pairs.py`: хеш группы новых нарезанных
фрагментов вычисляется для новой популяции. Полный speaker/session/original граф
проверяется на копиях метаданных; исходный dev-манифест остаётся побайтно прежним.
Это исправляет несовместимость group ID целых исходников с новой нарезкой.
Замороженный inference driver и критерии отбора не изменялись.

## Дополнительные готовые обучающие данные

Явное получение и проверка файлов на host Python 3.11+:

```sh
python scripts/acquire_training_support.py
```

Нужны сохранённые `librispeech-api.json` и `fleurs-api.json` в
`data/input/pair-quality-sources-v1`; script проверяет pinned revisions, лицензии,
размеры и издательские SHA-256/Git blob SHA-1. API URL:
`https://huggingface.co/api/datasets/openslr/librispeech_asr?blobs=true` и
`https://huggingface.co/api/datasets/google/fleurs?blobs=true`.
Не подменяйте метаданные другой ревизией. Загрузчик умеет продолжать `.part` только
после подтверждения HTTP Range сервером.

Импорт реализован в `scripts/import_training_support.py` и реально запущен в
`north55-training-support-import-v1` на `north55-speech-train:publisher-v2`, без
сети и GPU. Переданы `/support`, `/prepared`, `/clean-plan.json`,
`/additional-plan.json`, `/fleurs-dev.tsv`, `/study` и `/audio`. Фактические mounts
и команда сохранены в снимке контейнера. Первый отказ импорта и исправление
буквальных кавычек TSV сохранены в `import-attempt1.json`; source text не менялся.

## Проверки и следующий этап

Проверка новых контрактов использует `tests/test_quality_pairs.py`,
`tests/test_quality_pair_groups.py`, `tests/test_training_support_import.py` и
`tests/unit/test_publisher_training.py`. Аудит измеренных файлов выполняет
`scripts/verify_quality_pairs.py`; Markdown рендерит
`python scripts/report_quality_pairs.py`. Тесты с синтетическими строками
проверяют отказы и не считаются доказательством качества ASR.

Общие команды host Python для PowerShell/Linux:

```sh
python scripts/quality_pairs_artifacts.py snapshot
python scripts/quality_pairs_artifacts.py verify
python scripts/quality_pairs_artifacts.py report
```

Для существующего verifier-контейнера явно добавляйте `--resume` к `verify`.
`python scripts/quality_pairs_artifacts.py import` запускает полный изолированный
импорт с необходимыми mounts; `import --resume` продолжает существующий контейнер.
Снимки не содержат переменные окружения с секретами.

Бюджет предыдущего dev-поиска: 16/16. Контракт требует остановки поиска после
исчерпания бюджета, поэтому обучение с последующим выбором по dev в этом этапе
заблокировано. Для следующего сравнения нужен отдельно согласованный протокол
дополнительного эксперимента. Пороги качества, baseline и final test не менялись.
Ни точность новых машинных пар, ни требуемое снижение WER этим этапом не установлены.
