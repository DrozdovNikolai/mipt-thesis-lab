# Переобучение с равномерной EN-выборкой

Один опыт `balanced-v1` проверяет политику отбора EN-данных. В старом импорте
использовались первые 200 пригодных записей издательского файла от двух дикторов.
В новом выбраны 200 записей от 19 дикторов; новая ручная разметка не нужна.
Общие готовые тексты корпуса не объявляются кабинетными эталонами.

Фиксированный протокол: [protocol.md](../reports/balanced-v1/protocol.md).
Итоговые измерения и ограничения: [report.md](../reports/balanced-v1/report.md).

## Выборка и неизменные условия

`north55_speech.sampling.balanced_selection` получает только допущенные train
записи с известным speaker ID. Дикторы и записи упорядочиваются по SHA-256 от
seed 55 и ID; затем от каждого диктора по очереди выбирается одна запись.
Исчерпанные группы пропускаются. При недостатке записей эксперимент останавливается.
Проверяются длительность 1–30 с, частота/каналы, числа с плавающей точкой, дубликаты
декодированного аудио, происхождение и отсутствие пересечений с известным dev.

Получены 200 EN-примеров, по 8–11 на диктора. Из прежних 200 сохранились 18.
EN длительность 44,30 → 42,70 мин, всего 91,50 мин. Другой состав фраз и
длительностей ограничивает причинный вывод о числе дикторов.

Те же 200 RU и 33 слабые кабинные записи остаются в тех же позициях, со всеми
прежними метаданными. Dev содержит прежние 35 слабых пар побайтно. Исходные
манифесты не перезаписываются; новые находятся в `data/curated/balanced-v1`.
Аудио EN записано в `/audio/balanced-v1` существующего Docker volume.

Обучение использует точную копию прежнего `lora.py`, тот же исходный checkpoint,
Docker image, seed 55, rank 8, learning rate 0.0001, 120 шагов и единственное
сохранение/evaluation на шаге 120. Финальный checkpoint выбран до обучения.
Новые веса в `north55-speech_model_cache`:

```text
/models/whisper-small-balanced-v1/adapter
/models/whisper-small-balanced-v1/merged
/models/whisper-small-balanced-v1/checkpoints/checkpoint-120
/models/whisper-small-balanced-v1-ct2
```

## Исполненные команды

Из корня репозитория в PowerShell:

```powershell
python scripts/prepare_balanced_split_metadata.py
python scripts/run_balanced_retraining.py freeze
python scripts/run_balanced_retraining.py tests
python scripts/run_balanced_retraining.py prepare
python scripts/run_balanced_retraining.py train
python scripts/run_balanced_retraining.py freeze-eval
python scripts/run_balanced_retraining.py infer
python scripts/run_balanced_retraining.py cpu
python scripts/balanced_artifacts.py
python scripts/report_balanced_retraining.py
```

`freeze`, `train`, `freeze-eval` не перезаписывают существующие результаты. Полный
повтор обучения требует отдельного окружения с исходными данными и весами; не
удаляйте рабочие volumes. Исторические артефакты являются частью воспроизводимости.
Все stage-контейнеры работают с `--network none`; GPU 0 — RTX 5070 Ti.

Для первоначального prepare нужны файлы `split-metadata/clean-plan.json` и
`split-metadata/reviewed-dev.jsonl`. Они содержат только метаданные известного
контроля/групп: эталоны, labels, сущности и временные события удалены из копий.
Источник — прежние `data/curated/clean-controls-v1/plan.json` и
`data/curated/reviewed-pilot-v2/dev.jsonl`; оригиналы сохранены. Эти локальные
копии исключены из Git, как и данные, поэтому одного клона недостаточно.
`prepare_balanced_split_metadata.py` воспроизводит первоначальные копии и
подтвердил их побайтное совпадение; существующие отличающиеся копии не заменяются.

Повторное распознавание проверяет frozen identity и пропускает уже выполненные
675 запросов. Сохранённая ошибка требует отдельного разбора, не скрытого повторения.
Это восстановление завершённого inference, а не проверка аварии во время обучения.

Linux/WSL использует те же Python runners:

```sh
python3 scripts/run_balanced_retraining.py infer
python3 scripts/balanced_artifacts.py
python3 scripts/report_balanced_retraining.py
```

На Windows-хосте вызов выполняется через Ubuntu WSL с абсолютным путём скрипта.
Если Linux не может прочитать приватный артефакт UID 10001, reporter читает его
в отдельном offline-контейнере того же владельца, без расширения прав.

## Оценка и решение

675 новых ответов: прежние 661 диагностический вход и 14 тихих копий с теми же
reference IDs и группами. Baseline и прежняя LoRA сравниваются по 1350 сохранённым
ответам с проверенными хешами. Inference не получает их или эталоны. Во всех
качественных сравнениях обычный декодер и CUDA float16; четыре CPU int8 smoke
проверяют только исполнение. Изменение checkpoint учитывается отдельно от
same-checkpoint улучшения pipeline.

Скорер зафиксирован до inference в `reports/balanced-v1/scoring`; пороги и
lexical normalizer прежние. Сохраняются все S/D/I/N, bootstrap CI, шумовые вставки
и повторяющиеся триграммы. Последние могут соответствовать настоящему повтору,
поэтому не используются для удаления текста или выдачи temporal event labels.

Независимые ASR/сущности/NLP/temporal gate требуют данных сверх пяти известных
кабинных dev-фрагментов. При отрицательном результате гипотеза о данной выборке
останавливается. Новая модель не продвигается в release из этой диагностики.

## Итоговый checklist

- [x] Подготовлены и проверены 200 EN-пар от 19 дикторов; остальные 233 записи
      и dev сохранены. 26 контрактных тестов прошли.
- [x] Одно обучение на 120 шагов выполнено; все 433 примера загружены.
- [x] Выполнены конвертация и реальный GPU smoke сохранённых весов.
- [x] Получены 675 GPU-ответов и 4 CPU smoke без runtime failures.
- [x] Сравнение с исходным checkpoint и прежней LoRA выполнено.
- [x] Resume через Linux сохранил все 675 ответов; scorer и reporter дали
      побайтно одинаковые артефакты в PowerShell и Ubuntu WSL.
- [x] 47 проверок целостности/исполнения прошли; сервис отвечает ready на baseline.
- [ ] Цель WER: FAIL. Новая LoRA 23,48%, прежняя 22,61%, исходная 13,91%
      на пяти кабинных dev-фрагментах. Вставок 17 против 5 у исходной модели.
- [ ] Noise guard: FAIL. Независимая ASR/сущности/NLP/temporal оценка:
      NEEDS_MORE_DATA. Release не продвинут.

Конкретный вариант перебалансировки не помог. Он остановлен без новых проб по
тем же dev-ответам. Это не доказывает бесполезность разнообразия данных вообще.
Два технических отказа вспомогательного воспроизведения метаданных (CRLF и права
чтения WSL) сохранены как `split-metadata-replay-attempt*.json`; исходные файлы,
пороги и обучение при исправлении helper не менялись.
