# Данные получены, подготовка возобновлена

Пользователь уже предоставил источники в `SOURCES.md`. Предыдущая остановка по
отсутствию готовых manifests была преждевременной: скачать и подготовить доступные
корпуса можно без достаточного объёма финального test. Подготовка manifests не
возлагается на пользователя. Исторический `blocker-audit.json` сохранён.

| Источник | Фактически получено | Текущее использование |
|---|---|---|
| BLeRIOT-A v1.0 | RAR 1,710,792,035 байт; 40 WAV, 260.44 минуты; 15 PDF/DOCX/TXT | Все 40 записей декодированы и импортированы для review |
| BLeRIOT-C v1.0 | ZIP 863,744,696 байт; 28 WAV, 80.84 минуты | 15 вариантов связаны с A по именам, длительности и огибающей; 13 требуют дополнительной проверки |
| VOICI 2660112 | WAV 289,616,504 байта, 50.28 минуты; PDF-описание | Отдельный источник фонового шума; предполагается только train/dev |
| RU aviation commands | Проверены API и полная карточка, 1,182 примера | В карточке отсутствуют лицензия и подтверждение происхождения человеческих записей; аудио не импортировано |

Для архивов/файлов совпали опубликованные MD5, записаны SHA-256. BLeRIOT используется
локально для некоммерческой дипломной работы по CC BY-NC 4.0. VOICI — CC BY-SA 4.0;
производные данные не публиковались и не включались в release.

Данные находятся в `data/input/bleriot/verified/` и `data/input/voici/`.
Исходные архивы сохранены. Файлы `.part` и `.chunks-*` являются диагностическими
остатками/кэшем докачки и не поступают в importer. Каталог `bleriot/extracted/c`
содержит результат первой распаковки, при отчётности используется только `verified/c`.

Подготовлено 55 записей: 39 train, 10 dev, 6 зарезервированных test; группы по
дикторам — 12/3/3. Варианты сохраняют исходные speaker/session/original IDs.
Даты отдельных сессий не опубликованы; группировка по reader является явным
допущением. Между splits есть общие тексты сценариев; это отражено в split-report.
У 12 файлов C имя и длительность соответствуют A, но простая проверка огибающей
дала корреляцию ниже заранее заданных 0.5. Это не доказывает неверную связь:
нужна более надёжная проверка; нельзя строить окончательную оценку только на более
лёгких шумовых записях. У `CVR_BEA_cvr_sp03_.wav` дополнительно не установлен
точный оригинал. Все 13 файлов сохранены для дальнейшего разбора.

Manifests и шаблоны review: `data/curated/bleriot-v1/`. Тестовые references
находятся в `sealed/`, не монтировались в ASR-процесс. Ни один Sample не получил
автоматический `human_verified`; scope и язык сегментов требуют проверки.

Выполнены четыре реальных offline CPU ASR-прогона: один и тот же dev-фрагмент
чеклиста PC7, 30–60 секунд оригинала и его шумовой версии, baseline и VAD.
Везде одна модель `small`, `int8`, CPU, без cache hit и сети. Проверены непустые
гипотезы, одинаковые веса/precision и перенос таймкодов в оригинал. На этих
черновиках заметны ошибочные переключения языка после VAD и повторы на шумовой
записи. Число сегментов не является метрикой качества. **WER/F1 и улучшение не
оценены; candidate не выбран и не продвинут.**

Итог: проверка acquisition/import/smoke — PASS; научная приёмка —
**NEEDS_MORE_DATA**. Это разные проверки. Нужны выравнивание и сверка человеческих
транскриптов, независимая разметка сущностей/событий/значимости/временных границ,
segment scope и достаточный независимый final test. 3 зарезервированные группы
не выполняют минимум 20 из ACCEPTANCE.yaml. PC7 PDF содержит четыре страницы
сканов без текстового слоя: OCR/выравнивание также должны сохранять статус черновика.

Воспроизведение получения и распаковки на PowerShell, Python 3.11+ и установленный
7-Zip; команды выполнены в этой рабочей папке:

```powershell
python scripts/acquire_bleriot.py --noncommercial-research
python scripts/acquire_voici.py
python scripts/extract_bleriot.py --output data/input/bleriot/verified
```

Acquisition поддерживает повторный запуск и докачку; существующие архивы снова
проверяются. Распаковка требует пустого каталога назначения. Не удалять текущие
данные ради повторения: использовать новый `--output` при необходимости.

Для Linux те же скрипты запускаются `python3`, а распаковщику можно передать
`--seven-zip 7zz`. Повтор acquisition с уже скачанными архивами проверен также
в Linux Docker. Полную загрузку крупных файлов второй раз с Linux не повторяли.

Подготовка и ASR выполнялись в Linux CPU-образе Docker. Эти команды одинаковы для
PowerShell и Linux shell при запуске из корня проекта; каталоги должны быть доступны
на запись пользователю контейнера. Подготовка v1 и отчёт smoke неизменяемы: повтор
на существующих выходах намеренно откажется, чтобы сохранить измерения.

```sh
docker run --rm --network none -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/data/input:/data/input" -v "${PWD}/data/curated:/data/curated" -v "${PWD}/reports:/reports" -v north55-speech_audio_data:/audio --entrypoint python north55-speech:0.1.0 scripts/prepare_bleriot.py
docker run --rm --network none -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/data/curated/bleriot-v1/manifests/train-dev:/data/train-dev:ro" -v "${PWD}/reports:/reports" -v north55-speech_audio_data:/audio -v north55-speech_model_cache:/models:ro -v north55-speech_artifact_data:/artifacts --entrypoint python north55-speech:0.1.0 scripts/bleriot_smoke.py
```

Проверки: 13 тестов безопасности архивов, Ruff и mypy для новых скриптов;
реальная распаковка, полный decode/import, проверка partition proof и четыре ASR
исполнения. Основной код приложения и исходные требования не изменены.

Подробные доказательства: `data-resumption.json`, `bleriot-acquisition.json`,
`bleriot-preparation.json`, `bleriot-asr-smoke-plan.json`, `bleriot-asr-smoke.json`,
`voici-acquisition.json`, `source-acquisition-tests.xml`.

Источники: [BLeRIOT-A](https://doi.org/10.57745/EWXJLT),
[BLeRIOT-C](https://doi.org/10.57745/ASYVFP),
[VOICI](https://zenodo.org/records/2660112),
[RU карточка](https://huggingface.co/datasets/NLPVladimir/aviation-command-dataset-ru).
