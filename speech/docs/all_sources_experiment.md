# Расширенный опыт на имеющихся источниках — 2026-09-14

**Исполнение завершено; улучшение для выпуска не доказано.** Новая LoRA не
достигла точечной цели 10% на доступном чистом кабинном dev и провалила шумовой
диагностический guardrail. Рабочий baseline сохранён. Итоговые ASR/NLP/temporal
quality gates — **NEEDS_MORE_DATA**, независимый final test не открывался.

Все числа: [измеренный отчёт](../reports/all-sources-v1/report.md),
[машиночитаемые метрики](../reports/all-sources-v1/evaluation/comparison.json),
[проверка артефактов](../reports/all-sources-v1/verification.json).
Это продолжение прежних опытов, а не переименование их результатов.

## Что использовано

Проверены все ранее обсуждавшиеся источники. Локально доступны BLeRIOT-A/C,
VOICI и LibriSpeech; сохранённые пользовательские ревизии использованы без
редактирования. HTTP-ответы и причины допуска:
[source-decisions.json](../reports/all-sources-v1/source-decisions.json),
[retrieval.json](../reports/all-sources-v1/source-audit/retrieval.json).

| Источник | Выполненная работа | Ограничение |
|---|---|---|
| BLeRIOT-A/C | 476 полных окон: 440 A и 36 C, 15 исходных записей; исходное разделение 9 train / 3 dev групп | Издательский сценарий после автоматической привязки остаётся слабым эталоном |
| BEA, Beech, PC7, TBM940 | Обработаны все полные train/dev окна этих документированных EN checklist-семейств | TBM940 обработан, но ни одна пара не прошла допуск; французские, CVR/ATC и неизвестные семейства не входят в эту EN адаптацию |
| VOICI | Все 50,2806 мин: 151 окно; дополнительно 204 смеси с BLeRIOT-A при 0/10 dB | Один исходник, целиком dev; речь удалена по заявлению издателя, местной независимой проверки нет; не допущен в обычную training augmentation |
| LibriSpeech | Повторены прежние 50 фиксированных общих чистых контролей, 39 читателей | Регрессионный контроль; обычная английская речь не подтверждает качество речи в кабине |
| Пользовательские ревизии | 5 прежних человеческих dev-расшифровок, 3 группы, 115 lexical words | Подсказки ранее показывались; запись чисел не уточнена; это не независимый final test |
| HIWIRE | Повторная проверка каталога | BLOCKED: лицензированного архива нет, покупка не выполнялась |
| RU aviation-command | Прочитаны текущие API, README, discussions | NOT_ADMITTED: не установлены лицензия и происхождение человеческих записей; названия voice-полей не доказывают синтез |
| IEM / DLR | Получены и изучены публикации, включая реальный PDF IEM | BLOCKED: не найдена разрешённая поставка аудио и транскриптов; статья не заменяет корпус |
| ATCOSIM / ATCO2 / UWB-ATCC | Проверка области | EXCLUDED: pilot–ATC вне основной задачи |

Конечные хвосты BLeRIOT короче 20 секунд перечислены в плане и отложены,
не дополнены предполагаемыми словами. Принятые пороги alignment, anchors и
проверки чисел не ослаблялись. Дополнительно отклонены предложения, для которых
alignment-модель определила язык не EN; это машинный фильтр, а не человеческое
подтверждение языка. Из 362 train / 114 dev окон допущены **33 train / 35 dev**
слабых пар (5 / 2 группы). Все отклонения сохранены. Clean/noisy варианты
связаны исходным графом; VOICI никогда не разделяется между train/dev/test.

## Обучение и измерения

Заранее задан один запуск: whisper-small, rank 8, lr 0.0001, seed 55,
40 optimizer steps. Реальное обучение заняло 50,015 с на RTX 5070 Ti;
сохранены adapter, merged weights, CT2, checkpoints и trainer history.
Weak dev loss: 1,404525 → 1,335019. Убывание loss не означает улучшение WER.

Parent — CT2-конверсия того же pinned Transformers checkpoint, обе модели
исполнены с фактическим CUDA/float16, beam 5 и temperature 0. VAD/chunking,
hints, denoise и повторное распознавание в сравнении выключены. VAD использован
только для определения активного RMS при подготовке SNR смесей. Новый checkpoint
не продолжает старую LoRA и не заменяет рабочую модель.

До inference заморожены конфигурация, код, эталоны, исходники и веса:
[evaluation/plan.json](../reports/all-sources-v1/evaluation/plan.json).
Исполнены все **524 × 2 = 1048** распознаваний, включая окна без допустимого
эталона. Невозможно посчитать WER для отсутствующего эталона; такие ответы
сохранены и не превращены в безошибочные примеры.

| Поднабор | Parent → expanded LoRA | Вывод |
|---|---|---|
| 35 слабых чистых dev-эталонов | 201/879 → 203/879; 22,87% → 23,09% | Относительное снижение −1,00%; FAIL_POINT_TARGET |
| 5 человеческих dev-эталонов | 34/115 → 36/115; 29,57% → 31,30% | Относительное снижение −5,88%; FAIL_POINT_TARGET, статистически INCONCLUSIVE |
| 50 общих clean controls | 44/1214 → 44/1214; 3,6244% → 3,6244% | Диагностический clean tolerance PASS; не общий quality PASS |
| 35 слабых эталонов смесей 0 dB | 564/879 → 480/879; 64,16% → 54,61% | Улучшение proxy 14,89%, один общий шумовой исходник |
| 35 слабых эталонов смесей 10 dB | 358/879 → 238/879; 40,73% → 27,08% | Улучшение proxy 33,52%, один общий шумовой исходник |
| VOICI по пустому эталону издателя | 555 → 706 слов; 11,0381 → 14,0412 слова/мин | Диагностический noise guardrail FAIL |

95% paired cluster bootstrap, 2000 повторов, seed 55, delta = new − parent:
человеческий dev **[−0,021739; +0,043478]**, 3 группы;
слабый чистый dev **[0; +0,002703]**, 2 группы.
В смесях одна noise-группа, поэтому bootstrap вырожден и не подтверждает
статистической значимости. Более низкая ошибка по слабому сценарию шумовой
смеси не устанавливает его фактическую разборчивость человеком.

Неразмеченные критические сущности, события и значимость не получили
автоматических «человеческих» меток. NLP precision/recall/F1 против rules
на этом материале не измерены; temporal event detection не заявлен.
EN/RU/mixed технически поддерживаются, независимое качество не подтверждено.

## Исполнение и проверка

| Этап | implemented | executed | verified |
|---|---|---|---|
| Аудит источников и подготовка | yes | реальные HTTP и 476 окон | provenance, hashes, split graph |
| LoRA train/merge/CT2 | yes | 40 шагов на GPU без сети | trainer history, 33/35 input hashes, веса |
| Сравнение и SNR | yes | 1048 ответов, 204 смеси | независимый edit distance и реконструкция всех смесей |
| CPU нового checkpoint | yes | реальное аудио без сети | PASS исполнения; actual compute type int8_float32 |
| Новые контракты | yes | 5 tests | PASS; это не повтор всей исторической 248-test suite |
| Пересчёт PowerShell и Linux/WSL | yes | обе команды score | JSON/CSV идентичны по SHA-256 |
| Восстановление после сбоя диска | yes | прерывание и продолжение | 707 прежних hashes сохранены, 341 ответ добавлен |
| Научный quality gate | yes | честная проверка достаточности | NEEDS_MORE_DATA; независимый final test NOT_RUN |

Во время первого inference произошёл **OSError Errno 5 при записи на диск**.
Контейнер завершился с кодом 255; сохранены его состояние, журнал и hashes
707 готовых ответов. После `docker start north55-expanded-evaluation-v1`
дописаны оставшиеся 341 ответа по тому же плану/runtime. Итоговый exit code 0,
исключений исполнения ASR в сохранённых per-sample результатах 0, инфраструктурных прерываний 1.
Несохранённая гипотеза прерванного вызова недоступна; её результат не выдуман.
Причина сбоя нижележащего хранилища не установлена.

PostgreSQL и RabbitMQ после остановки Docker также оставались выключенными.
Добавлен `restart: unless-stopped` в Compose и действующие контейнеры;
они подняты с прежними volumes. Проверены Compose config, health БД/брокера,
HTTP 200 API `/health/ready` и annotation UI. Повторная принудительная остановка
Docker для проверки новой политики не выполнялась. Доказательства:
[resumption](../reports/all-sources-v1/resumption/attempt-1.json).

## Проверенные команды пересчёта

Нужны уже сохранённые данные/отчёты, Docker volumes `north55-speech_audio_data`,
`north55-speech_model_cache` и CPU image `north55-speech:login-fix-v1`.
Scripts не скачивают данные и не открывают test. `score` пересчитывает метрики
по прежним ответам; `report` строит текст/графики; `verify` проверяет артефакты.
Верификацию запускайте последней, поскольку она фиксирует hashes отчётов.

PowerShell, из корня репозитория:

```powershell
./scripts/all_sources_report.ps1 score
./scripts/all_sources_report.ps1 report
./scripts/all_sources_report.ps1 verify
docker compose config -q
```

Linux, из корня репозитория с доступом к тому же Docker engine и данным:

```sh
sh scripts/all_sources_report.sh score
sh scripts/all_sources_report.sh report
sh scripts/all_sources_report.sh verify
```

Реально проверен Linux/WSL Ubuntu `score`, с вызовом из PowerShell:

```powershell
wsl -d Ubuntu -- sh /mnt/c/DEV/MIPT/Diploma/Speech/scripts/all_sources_report.sh score
```

PowerShell `score/report/verify` выполнены. Linux `report/verify` используют
тот же runner, но отдельного исполнения этих двух действий в WSL не было.
[Результат двух реальных пересчётов](../reports/all-sources-v1/score-reproduction.json).

## Повтор подготовки и обучения в чистом окружении

Ниже зафиксированы исполненные команды; в текущем окружении их выходы уже
существуют. Trainer отказывается перезаписывать модель. Полный новый опыт
требует отдельной версии выходных путей и нового плана до inference; прежние
версии не удалять. `infer` в существующем контейнере безопасно продолжает
план, проверяя совпадение runtime/config/audio/model и пропуская готовые ответы.
Отчёты сохраняют IDs образов, фактические команды и mounts каждого контейнера.

```powershell
# Документы (Poppler в annotation-tools).
docker run --rm --network none --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/data/curated/publisher-expanded-v1:/expanded" -v "${PWD}/data/input/bleriot/verified/a/raw-speech_transcript:/source-documents:ro" -v "${PWD}/data/curated/bleriot-documents/v1:/extracted:ro" north55-annotation-tools:0.1.0 -m scripts.expand_publisher_pairs documents

# Слабая привязка только train/dev; первый supported GPU.
docker run --name north55-expand-publisher-v1 --network none --gpus all -e CUDA_VISIBLE_DEVICES=0 -e HF_HUB_OFFLINE=1 --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/src:/app/src:ro" -v "${PWD}/data/curated/publisher-expanded-v1:/expanded" -v "${PWD}/data/curated/bleriot-v2/manifests/train-dev:/train-dev:ro" -v north55-speech_audio_data:/audio -v north55-speech_model_cache:/models:ro north55-speech-gpu:0.1.0 -m scripts.expand_publisher_pairs align

# Обучение с заранее заданным бюджетом, без сети.
docker run --name north55-expanded-training-v1 --network none --gpus all -e CUDA_VISIBLE_DEVICES=0 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/src:/app/src:ro" -v "${PWD}/configs:/app/configs:ro" -v "${PWD}/data/curated/publisher-expanded-v1:/expanded:ro" -v "${PWD}/reports:/reports" -v north55-speech_audio_data:/audio:ro -v north55-speech_model_cache:/models north55-speech-train:publisher-v2 train asr --config /app/configs/asr_lora_expanded.yaml

# Полный источник VOICI, dev only.
docker run --rm --network none --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/data/input/voici:/voici:ro" -v "${PWD}/data/curated/voici-diagnostic-v1:/voici-diagnostic" -v north55-speech_audio_data:/audio north55-speech:login-fix-v1 -m scripts.prepare_voici_diagnostics

# Фиксированные смеси, controls и заморозка до inference.
docker run --rm --network none --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/src:/app/src:ro" -v "${PWD}/configs:/app/configs:ro" -v "${PWD}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" -v "${PWD}/data/curated/publisher-expanded-v1:/expanded:ro" -v "${PWD}/data/curated/voici-diagnostic-v1:/voici-diagnostic:ro" -v "${PWD}/data/curated/clean-controls-v1:/clean-controls:ro" -v "${PWD}/data/curated/reviewed-pilot-v2:/reviewed:ro" -v "${PWD}/reports:/reports" -v north55-speech_audio_data:/audio -v north55-speech_model_cache:/models:ro north55-speech:login-fix-v1 -m scripts.evaluate_expanded_sources prepare

# Все 1048 ответов, локально, без сетевого доступа и эталонного текста в prompts.
docker run --name north55-expanded-evaluation-v1 --network none --gpus all -e CUDA_VISIBLE_DEVICES=0 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/src:/app/src:ro" -v "${PWD}/configs:/app/configs:ro" -v "${PWD}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" -v "${PWD}/reports:/reports" -v north55-speech_audio_data:/audio:ro -v north55-speech_model_cache:/models:ro north55-speech-gpu:0.1.0 -m scripts.evaluate_expanded_sources infer
```

Это команды реального GPU выполнения из PowerShell; отдельный полный повтор
обучения под Linux не заявлен. Существующие образы собраны по Dockerfile и
Dockerfile.train; подготовка исходных BLeRIOT/контролей описана в
[review_packet.md](review_packet.md), [publisher_experiment.md](publisher_experiment.md)
и [clean_controls.md](clean_controls.md).
