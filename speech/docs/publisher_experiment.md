# Выполненный эксперимент на готовых текстах

Издательские PDF/DOCX BLeRIOT уже использованы для настоящего обучения.
Повторная ручная транскрипция всего корпуса не нужна для этого пути.
**Научная приёмка остаётся NEEDS_MORE_DATA; статистическое подтверждение —
INCONCLUSIVE. Candidate не выбран и не включён в release.**

Измерения: [отчёт](../reports/publisher-weak-v1/report.md),
[полные результаты и гипотезы](../reports/publisher-weak-v1/comparison.json),
[CSV](../reports/publisher-weak-v1/comparison.csv),
[проверка исполнения](../reports/publisher-weak-v1/verification.json).

## Данные и допущения

Источник — уже скачанные BLeRIOT-A/C, разрешённые для некоммерческого
исследования по CC BY-NC 4.0. Учитываются ограничения исходного датасета и весов;
полученная модель не объявляется свободной от ограничений обучающих данных.
Использованы английские checklist-сценарии BEA, Beech и PC7. CVR-семейства
с ATC, французские сценарии, неподтверждённые C-parent связи и test исключены.
Английский язык задан по документам, не по подтверждённой аудиоразметке.

PDF с двумя колонками ранее извлекался в неверном порядке: соседние чек-листы
перемешивались построчно. Теперь порядок восстанавливается по координатам
Poppler. Нормализация убирает типографскую нумерацию и dot leaders, не исправляет
произнесённые числа «по смыслу». Сохраняются исходный документ, его SHA-256,
извлечённый текст, оригинальное аудио и смещение каждого окна.

До выполнения зафиксированы окна 30, 60, 90, 120, 150, 180 секунд длительностью
20 секунд, пороги сопоставления и бюджет обучения. Подготовлено 76 окон:
52 train и 24 dev, соответственно 8 и 3 speaker-группы. Автоматические проверки
допустили 17 train (340 секунд, 5 групп) и 7 dev (140 секунд, 3 группы).
Оставшиеся 52 окна и причины отказа сохранены. Clean/noisy варианты относятся
к одной группе и split; сценарии могут повторяться между train/dev, поэтому
обобщение на новые сценарии не заявляется. Все 24 dev-окна распознаны обеими
моделями, включая 17 без пригодного эталона.

Локальный Whisper сопоставляет издательский текст с аудио через attention/DTW.
Пороги: не менее 45% покрытия точными якорями и 8 совпавших токенов, медиана
модельной оценки слова не менее 0,35, доля нулевых длительностей не более 0,25.
Эта оценка не является калиброванной вероятностью правильности. Несогласие
числовых последовательностей исключает пару из обучения, а не исправляет её.
Принадлежность к cockpit/read speech предварительная; `primary=false`,
`scope_verified=false`, `transcript_status=weak` (или missing при отсутствии текста).
Меток событий, значимости, критических сущностей и ролей этот процесс не создаёт.

Планы и контрольные суммы: `data/curated/publisher-weak-v1/plan.json` и
`reports/publisher-weak-v1/comparison-plan.json`. Ни test-эталоны, ни test-аудио
не монтировались в подготовку, обучение или сравнение.

## Реальные результаты

LoRA обучалась 40 optimizer steps, rank 8, learning rate 0,0001, seed 55,
8 эпох, 52,805 секунды на RTX 5070 Ti. Это ограниченный пилотный эксперимент,
а не полноценная оптимизация по независимому dev WER. Dev loss снизился
с 1,9290 на шаге 10 до 1,8531 на шаге 40; cross-entropy не выдаётся за WER.
Первый запуск с двумя видимыми GPU остановился на нулевом шаге из-за
несовместимого GTX 1080 Ti. Неудачный запуск и его каталог сохранены;
успешный запуск использовал `CUDA_VISIBLE_DEVICES=0` и новый output v2.

Для сравнения исходный `openai/whisper-small` из того же локального
Transformers checkpoint отдельно конвертирован в CT2 float16. Обе модели
использовали одинаковые beam=5, temperature=0 и остальные настройки baseline,
без hints/VAD/denoise/redecode. Это **A5: разные веса после адаптации**,
отдельный опыт от A0–A4 с неизменными ASR-весами/precision.

| Измерение | Исходная модель | LoRA | Ограничение |
|---|---:|---:|---|
| Расхождения с автоматически привязанным dev-текстом | 70/178 = 39,33% | 57/178 = 32,02% | 7 окон, 3 группы; зависимый машинный эталон |
| В том числе S / D / I | 59 / 4 / 7 | 34 / 16 / 7 | Рост пропусков сохранён в отчёте |
| Общеречевой WER | 0/30 = 0% | 0/30 = 0% | 2 LibriSpeech записи одного читателя |
| Ошибки исполнения | 0 | 0 | Всего 52 реальных GPU inference |

Относительное снижение расхождений — 18,57%. Оно **не доказывает 10% снижения
истинного lexical WER**: привязка и допуск примеров зависят от родственного ASR,
а независимого gold нет. Доверительный интервал истинного эффекта не вычисляется
из этих зависимых меток. Два общеречевых контроля не закрывают требование
50 clean-control utterances. Критические сущности и NLP/temporal P/R/F1
остаются неизмеренными. EN/RU/mixed поддерживаются технически, качество
ни одного языкового режима пока не подтверждено.

Старые 64 A0–A4/dev-search inference сохранены без изменения. Вторичный
proxy-анализ всех восьми конфигураций на общей подвыборке из четырёх окон
сохранён в `ablation-proxy.csv`; он не выбирает победителя. Дополнительные
этапы не активированы. Независимый final test не запускался.

## Проверка и сохранённые модели

| Работа | implemented | executed | verified |
|---|---|---|---|
| Издательские документы → weak train/dev | да | 76 окон | hashes, split graph, provenance |
| LoRA → adapter → merged → CT2 | да | 40 шагов | сохранённые веса, history и hashes |
| Локальный adapted inference | да | CPU int8 и GPU float16 | сеть отключена; реальные аудио |
| Тесты приложения | да | 243, включая 9 integration | все прошли |
| Независимое улучшение ASR | да, протокол | final test не запускался | NEEDS_MORE_DATA |
| NLP и temporal event качество | да, обучение/метрики | только прежние тестовые fixtures | NEEDS_MORE_DATA |

Сохранены Docker volume `north55-speech_model_cache` и каталоги внутри него:

- `/models/whisper-small-publisher-lora-v2/adapter`, `merged`, `checkpoints`;
- `/models/whisper-small-publisher-lora-v2-ct2` — адаптированные CT2-веса;
- `/models/whisper-small-publisher-base-ct2` — точный исходный контроль;
- `/models/whisper-small-publisher-lora-v1` — первая неудачная попытка.

Полный набор тестов выполнен с исходным кодом успешного эксперимента.
После него добавлены только аннотации `Any` двух динамических объектов
Transformers/PEFT: дополнительные train-зависимости выявили неполные типы
сторонних API. Исполняемые операции обучения не изменены. Точная версия
исполнения сохранена как `lora-executed.py`; verification проверяет точную
поправку типов и отдельно записывает оба SHA. Обучение повторно не запускалось.
Прежняя проверка CPU E2E/queue recovery относится к serving baseline в
`reports/reporting-v1`; она не выдаётся за новый recovery-прогон LoRA.

## Команды

Все команды выполняются из корня проекта. Уже имеющиеся данные/веса не
скачиваются повторно. Docker сохраняет артефакты в named volumes. Успешное
обучение было реально запущено в PowerShell этой командой:

```powershell
docker run --rm --name north55-publisher-lora-v2 --network none --gpus all --entrypoint north55 -e CUDA_VISIBLE_DEVICES=0 -e NORTH55_REPORT_ROOT=/reports/publisher-weak-v1 -v "${PWD}/src:/app/src:ro" -v "${PWD}/configs:/app/configs:ro" -v "${PWD}/data/curated/publisher-weak-v1:/publisher:ro" -v "${PWD}/reports:/reports" -v north55-speech_audio_data:/audio:ro -v north55-speech_model_cache:/models north55-speech-train:0.1.0 train asr --config configs/asr_lora_publisher_attempt2.yaml
```

Повторный запуск обучения с тем же output корректно откажется перезаписывать
модель. Для нового опыта скопируйте config, задайте новое имя output и
отдельную версию измерений; старые отчёты/планы не перезаписывайте.

Упакованный образ с поправкой типов, сборка и проверка Compose выполнены:

```sh
docker build -f scripts/Dockerfile.refresh --build-arg BASE_IMAGE=north55-speech-train:0.1.0 -t north55-speech-train:publisher-v2 .
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.publisher-training.yaml --profile training config --quiet
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.publisher-training.yaml --profile training run --rm --no-deps trainer train asr --help
```

`Dockerfile.refresh` требует уже собранный base image и проверяет, что
`pyproject.toml`/`uv.lock` не изменились. Для чистой машины сначала используйте
`docker build -f Dockerfile.train -t north55-speech-train:0.1.0 .`.
GPU override выбирает один поддерживаемый GPU; publisher override отключает сеть.

Воспроизведение сохранённого сравнения (использует неизменные 52 inference records
при совпадающем плане), CPU smoke и рендер отчёта; PowerShell:

```powershell
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.publisher-training.yaml --profile training run --rm --no-deps --entrypoint python trainer -m scripts.evaluate_publisher_lora
docker run --rm --network none --entrypoint python -v north55-speech_model_cache:/models:ro -v north55-speech_audio_data:/audio:ro -v "${PWD}/reports:/reports" north55-speech-train:publisher-v2 -m scripts.test_publisher_cpu
docker run --rm --network none --entrypoint python -v "${PWD}/data/curated/publisher-weak-v1:/publisher:ro" -v "${PWD}/reports:/reports" north55-speech-train:publisher-v2 -m scripts.report_publisher_experiment
```

Linux host: те же команды Compose; для двух `docker run` замените `${PWD}`
на `$PWD`. Эта shell-подстановка эквивалентна; текущие измерения получены из
PowerShell в Linux-контейнерах, отдельный повтор обучения на Linux host не заявляется.

Проверка сохранённых измерений без повторного обучения, выполненная команда
PowerShell (Linux: `${PWD}` → `$PWD`):

```powershell
docker run --rm --network none --entrypoint python --mount "type=bind,source=${PWD}/data/curated/publisher-weak-v1,target=/publisher,readonly" --mount "type=bind,source=${PWD}/data/curated/bleriot-v2/manifests/train-dev,target=/train-dev,readonly" --mount "type=bind,source=${PWD}/data/curated/annotation-packet-v1/train.jsonl,target=/annotation/train.jsonl,readonly" --mount "type=bind,source=${PWD}/data/curated/annotation-packet-v1/dev.jsonl,target=/annotation/dev.jsonl,readonly" -v north55-speech_model_cache:/models:ro -v north55-speech_audio_data:/audio:ro -v "${PWD}/reports:/reports" north55-speech-train:publisher-v2 -m scripts.verify_publisher_experiment
```

Ранние технические ошибки проверки mounts и типизации сохранены отдельными
логами; окончательный статус относится к `verification.json`, а не к ним.

Подготовка исходных документов/пар воспроизводится через
`python -m scripts.build_publisher_pairs documents` и затем `align`.
Для первого действия нужны mounts `/source-documents` →
`data/input/bleriot/verified/a/raw-speech_transcript`, `/extracted` →
`data/curated/bleriot-documents/v1`, `/publisher` →
`data/curated/publisher-weak-v1`; используется существующий
`north55-annotation-tools:0.1.0` с Poppler и read-only `/app/scripts` из проекта.
Для `align` нужны только train/dev файлы из
`data/curated/bleriot-v2/manifests/train-dev` в `/train-dev`, publisher-каталог,
models/audio volumes и поддерживаемый GPU. Планы проверяются до повторного
исполнения; несовпадающую версию скрипта или конфигурации нельзя подменить.

Подробности API выравнивания:
[faster-whisper v1.2.1](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py),
[CTranslate2 Whisper.align](https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html).
