# NUS / Singapore Airlines VR: фактическая загрузка и проверка

Последующее действие: пользователь явно подтвердил использование для обучения.
Подтверждение и новый опыт сохранены отдельно в [nus-training-v1](../nus-training-v1/protocol.md).
Ниже — исторический результат первичного аудита до этого подтверждения.

Дата: 14 сентября 2026. **Загрузка и техническая проверка — PASS.
Допуск к обучению — BLOCKED: условия использования не установлены.
ASR/NLP качество — NEEDS_MORE_DATA; новых WER/F1 нет.**

## Что получено

Из [первичного репозитория](https://github.com/wangyubo013-blip/CDE4301-VR-401-Final-Report)
скачаны все 10 подготовленных Parquet-файлов, всего **34 631 443 байта**.
Revision: `0c520edbcd345cb9005cc77c3345eedbfef7147b`.
Размер и Git blob каждого файла сверены с опубликованным деревом, дополнительно сохранён SHA256.
Полные URL и hashes: [acquisition.json](acquisition.json).
Данные находятся в `data/quarantine/nus-vr-v1/`, уже исключённом из Git.
Авторы указывают связь проекта с Singapore Airlines – NUS Digital Aviation Corp Lab;
это проектный репозиторий, а не подтверждение официального открытого релиза данных авиакомпании.

| Файл | Строки |
|---|---:|
| CombinedSamples_01_03_04_05_06_07.parquet | 263 |
| Sample01.parquet | 16 |
| Sample01(1).parquet | 16 |
| Sample02.parquet | 50 |
| Sample02(1).parquet | 50 |
| Sample03.parquet | 36 |
| Sample04.parquet | 44 |
| Sample05.parquet | 61 |
| Sample06.parquet | 48 |
| Sample07.parquet | 58 |

Во всех **642 строках** есть декодируемый встроенный WAV, непустой текст, ID клипа и длительность.
Аудио: **16 kHz, mono, 1–13 секунд**. Декодированы все строки локально, без сети и GPU.
Пути из Parquet не открывались: использованы исключительно вложенные bytes.
Длительности по отсчётам совпали с полем duration в пределах 20 ms; полностью нулевых сигналов нет.
Это проверка контейнера и сигнала, не прослушивание и не подтверждение точности текста.

После сравнения декодированных PCM: **313 уникальных клипов, 329 повторных строк**.
Уникальное аудио: **1024,1 секунды = 17 минут 4,1 секунды**.
Combined содержит то же аудио, что Sample01 и Sample03–07; Sample02 добавляет 50 клипов.
Версии `(1)` не добавляют уникального аудио. Считать 642 независимыми примерами нельзя.
В уникальных references 1255–1258 слов по пробельной токенизации, в зависимости от версии текста;
это инвентаризация, не lexical WER scorer и не выбранный эталон.

## Почему данные пока не поданы в обучение

1. **Условия использования не установлены.** GitHub API возвращает `license: null`.
   Полное текущее дерево совпадает с закреплённой ревизией; файлов LICENSE/COPYING/terms/consent
   не найдено. README разрешает просмотр материалов, но не содержит условий обучения.
   В прочитанном отчёте также не найдено разрешение на переиспользование записей.
   Публичная доступность не записывается в provenance как установленное право обучения.
   Это основание из исходного запроса, SOURCES.md и ACCEPTANCE.yaml
   (`require_license_and_provenance: true`). Порог и правило не менялись.
2. **11 одинаковых аудиоклипов имеют разные тексты.** Различаются слова и формы слов,
   включая `control/controls` и `check/checked`; это не только регистр или пунктуация.
   Все версии сохранены. Инспектор не выбирает более правдоподобную версию и не исправляет числа.
3. **Во всех 642 строках start/end исходной записи — NaN.** Они сохранены в индексе как unknown/null,
   а не заменены нулём. В исходном ParquetGeneration.py подтверждён fallback NaN при отсутствии
   подходящих колонок. Опубликован TimelineTemplate.csv, но заполненных таблиц с границами
   для семи Sample в дереве нет. Время относительно клипа известно, относительно оригинала — нет.
4. **Не установлены независимые speaker/session IDs.** ID вида `clip01_0001` обозначает клип;
   семь Sample не доказывают семь разных экипажей. Весь источник пока одна консервативная группа.
   Train/dev/test не создан; открытые записи не могут стать новым независимым final test.
5. **Есть признаки радиообмена в source references.** В конфликтующих текстах встречается
   обращение к Busan Tower с позывным. Это требует отделения pilot–ATC и сценарных голосовых
   подсказок от общения экипажа. Проверки scope по аудио не было; автоматических human labels нет.

[Отчёт авторов](https://wangyubo013-blip.github.io/CDE4301-VR-401-Final-Report/)
описывает ручную привязку и проверку transcripts исследователями. Это заявленное происхождение,
а не наша сверка каждой пары. Их опубликованные результаты не являются результатами north55.
Даже 313 клипов без исключений не покрывают требования 3000 слов и 20 независимых групп.
Разметки критических сущностей, проектных категорий/значимости и temporal events здесь не обнаружено.

## Статусы работ

| Работа | implemented | executed | verified |
|---|---|---|---|
| Получение закреплённых Parquet с проверкой hashes | да | да | PASS, 10 файлов |
| Офлайн-декодирование, проверка полей и PCM-дубликатов | да | да | PASS, 642 строки |
| Повтор из PowerShell и Ubuntu WSL/Linux | да | да | Совпали измерения и приватный индекс |
| Тесты целостности, unknown timestamps, конфликтов чисел, аудио | да | да | 7 passed |
| Допуск к ASR inference / LoRA | существующий путь проекта | нет | BLOCKED, нет подтверждённых прав |
| Улучшение WER / NLP F1 / сущностей | существующие scorers | нет | NEEDS_MORE_DATA |
| Продвижение candidate в release | существующий gate | нет | BLOCKED для этого источника |

Изменений serving pipeline, baseline, ACCEPTANCE.yaml, SPEC.md и SOURCES.md нет.
Пользовательская разметка и прежние эксперименты сохранены. Письма, issues, покупки и внешние
ASR API не использовались. Полные references остаются в приватном локальном индексе под `data/`.
Не скачивались веса авторов, `test.wav`, физиология и видео с YouTube; код авторов не запускался.

Точная текущая проверка: [inspection-final.json](inspection-final.json).
Повтор: [inspection-linux-replay.json](inspection-linux-replay.json).
Сводная верификация: [verification.json](verification.json), **32 проверки PASS**.

Первая попытка `inspection.json` завершилась FAIL: инспектор ошибочно требовал исходные
таймкоды для учёта успешно декодированного клипа. Код сохранён как `inspect-initial.py`.
Исправление отделяет неизвестные таймкоды от ошибки аудио. Исходный FAIL, последующий
`inspection-v2.json` и финальная проверка сохранены; данные и условия допуска не исправлялись.

## Воспроизведение

Команды запускались из корня Speech. Для первоначального получения нужен Python 3.11+
и интернет; для офлайн-инспекции — локальный Docker image `north55-speech-train:publisher-v2`
с Python 3.11, PyArrow 25.0.1, soundfile 0.13.1 и NumPy 2.2.6.
Это существующий локальный image проекта, не образ из публичного registry.
Сначала получить metadata (каталог должен быть новым), затем payloads:

```text
python scripts/discover_direct_datasets.py --urls reports/nus-vr-v1/metadata-requests.json --output reports/nus-vr-v1/metadata
python scripts/acquire_nus_vr.py
python scripts/discover_direct_datasets.py --urls reports/nus-vr-v1/preparation-requests.json --output reports/nus-vr-v1/preparation-metadata
```

Получение уже скачанных файлов проверяет их целостность. Чтобы не переписать исходный
acquisition audit при повторе, передать `--report reports/nus-vr-v1/acquisition-replay.json`.
Если указанный acquisition report уже существует, загрузчик останавливается до изменений.
Инспекция отказывается перезаписывать существующий отчёт или приватный индекс;
при повторе выбрать новые пути в `--output` и `--private-index`.

PowerShell (реально выполнено с указанными final-путями):

```powershell
docker run --rm --network none --mount "type=bind,source=$($PWD.Path),target=/work" -w /work --entrypoint python north55-speech-train:publisher-v2 scripts/inspect_nus_vr.py --output reports/nus-vr-v1/inspection-final.json --private-index data/quarantine/nus-vr-v1/inspection-index-final.json
docker run --rm --network none --mount "type=bind,source=$($PWD.Path),target=/work" -w /work --entrypoint python north55-speech-train:publisher-v2 -m pytest -q tests/test_nus_vr_inspection.py --junitxml=reports/nus-vr-v1/unit-tests.xml
python scripts/verify_nus_vr.py
```

Linux (реально выполнено из Ubuntu WSL, cwd `/mnt/c/DEV/MIPT/Diploma/Speech`):

```bash
docker run --rm --network none --mount "type=bind,source=$PWD,target=/work" -w /work --entrypoint python north55-speech-train:publisher-v2 scripts/inspect_nus_vr.py --output reports/nus-vr-v1/inspection-linux-replay.json --private-index data/quarantine/nus-vr-v1/inspection-index-linux-replay.json
```

После установления прав этот источник можно рассмотреть как дополнительное обучение/dev:
сначала установить состав записей/участников, отделить ATC, исключить конфликтующие пары либо
подтвердить их версии и сохранить все связанные клипы в одной группе. Параметры эксперимента
фиксируются до измерений. Текущий объём сам по себе не даёт независимого подтверждения цели 10%.
