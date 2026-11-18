# north55_speech · «55 Север»

Локальный модуль речи экипажа и инструктора внутри кабины/тренажёра. Pilot–ATC
радиообмен не является целевой задачей. Результат — проверяемый **черновик** журнала,
а не подтверждение состояния самолёта или оценка квалификации пилота.

Работают FastAPI/UI, Celery/RabbitMQ, PostgreSQL/Alembic, локальный faster-whisper,
VAD, обработка каналов, нормализация, сущности, эпизоды, review и экспорт. CPU E2E и
реальные ASR smoke-тесты выполнены. Есть обучаемый NLP и отдельный LoRA train-path.
**Улучшение ASR/NLP на независимых cockpit-данных пока не подтверждено.**
Статусы и ограничения: [implementation_status](docs/implementation_status.md),
[model card](docs/model_card.md), [отчёты](reports/), [исходные требования](SPEC.md).

**Последний этап, 15 сентября:** согласованные правки Parakeet и Canary дали
небольшой выигрыш без новой ручной разметки: исходный кабинный dev WER
**13,04% → 11,30%**, тихие версии **13,91% → 12,17%**, шум 15 dB
**26,09% → 23,48%**. Это 15 → 13 ошибок на 115 словах исходных пяти частичных
ручных эталонов. Сильный шум сохранён; на 35 слабых dev **21,96% → 21,50%**.
Проверены 541 вход, 491 дополнительный одиночный Parakeet и полный локальный запуск
на шести файлах. Всего в v10/v11 — 1065 новых GPU ASR-вызовов, 16 тестов.
На retained-train есть ухудшение 5,20% → 5,65%; независимая приёмка INCONCLUSIVE.
Прямая замена на Canary и DeepFilterNet отклонены. Основной сервис сохранён.
[Итог и ограничения](reports/cockpit-consensus-v11/decision.md) ·
[Локальная команда](docs/cockpit_consensus_v11.md).

**Предыдущий этап:** обучен переключатель Whisper/Parakeet по
характеристикам шума на 3927 train-вариантах без текстовых меток. На пяти исходных
частично ручных dev WER сохранён **13,04%**, на их версиях с сильным искусственным
шумом **128,70% → 48,70%**; на 35 слабых шумных dev **57,22% → 51,65%**.
Обычная, тихая речь и 15 dB сохранены. На 60 неречевых входах пустой ответ;
есть потеря одной train-реплики правилом пустого Parakeet. Проверены все 541 вход,
3927 обучающих вариантов и четыре файла с 6 новыми реальными GPU ASR-вызовами.
Основной сервис сохранён, независимая приёмка не подтверждена.
[Результат](reports/cockpit-noise-router-v9/decision.md) ·
[Запуск на своём аудио](docs/cockpit_hybrid_local.md) · [Команды опыта](docs/cockpit_noise_router_v9.md).

**Предыдущий этап, 15 сентября:** выбор из двух ASR по вероятностям medium.en
ухудшил исходный кабинный WER 13,04% → 21,74% и сильный шум 128,70% → 135,65%.
Этот вариант отклонён; [его FAIL и проверки](reports/cockpit-selector-v8/decision.md) сохранены отдельно.

**Предыдущий этап, 15 сентября:** обучены два адаптера по 240 обновлений — контроль
на 247 парах и расширенная версия на 259 (18 новых, 6 вложенных старых заменены).
На пяти исходных частично ручных dev WER **13,04% → 16,52%**, на 35 слабых
**21,96% → 22,07%**. На тихих версиях есть небольшой выигрыш, устойчивого
улучшения кабинной речи нет; кандидат **FAIL**, рабочая модель сохранена.
1136 новых GPU ASR, 4 CPU ASR, 15 тестов; 1098 обучающих сигналов/меток и
1118 подсчётов ошибок повторно проверены. Новые blind-dev и test не использованы.
[Результат](reports/cockpit-data-v7/decision.md) ·
[Таблицы](reports/cockpit-data-v7/report.md) · [Команды](docs/cockpit_data_v7.md).

**Предыдущий этап, 15 сентября:** сравнили Parakeet с Whisper на идентичном звуке.
При сильном искусственном шуме на пяти старых кабинных dev WER **128,70% → 48,70%**
относительно адаптера v5, но на исходной речи **13,04% → 21,74%**. На 60 неречевых
входах Parakeet возвращает пустой текст без VAD. Повторная проверка 352 кандидатов
дала 18 слабых пар: 2,82 минуты нарезок, 2,36 минуты нового покрытия.
843 GPU ASR и проверка данных/ответов завершены; рабочая модель сохранена.
[Разбор результата](reports/cockpit-cross-asr-v6/decision.md) ·
[Таблицы](reports/cockpit-cross-asr-v6/report.md) · [Команды](docs/cockpit_cross_asr_v6.md).

**Предыдущий этап, 15 сентября:** завершены три обучения без новой ручной разметки:
равномерное, с балансировкой/420 акустическими вариантами и с 240 неречевыми примерами.
На пяти dev с искусственным шумом 15 dB WER **36,52% → 26,09%**; на исходных пяти
осталось 15 ошибок, как у прежнего режима. При сильном шуме качество ещё плохое,
без VAD ложных слов стало больше. VAD отсекает все 60 неречевых контролей и сохраняет
234 речевых. Дополнительное обучение молчанию не дало заметного эффекта.
1723 новых GPU ASR, 6 CPU ASR, 19 тестов; рабочая модель сохранена.
[Результат и ограничения](reports/cockpit-robust-v5/decision.md) ·
[Все метрики](reports/cockpit-robust-v5/report.md) · [Команды](docs/cockpit_robust_v5.md).

**Предыдущий этап, 15 сентября:** подготовлены 247 кабинных train-пар (29,06 минуты),
включая 25 новых сложных и 16 шумовых; обучены и проверены три режима на одних данных.
На пяти частично ручных dev: **16 → 15 ошибок**, WER 13,91% → 13,04%; на 35 слабых
dev: 22,87% → 21,62%. Убедительный перенос пока не подтверждён, ложные слова на шуме
участились. Рабочая модель сохранена. Выполнены 2141 GPU-распознавание с подготовкой
и 6 CPU-проверок. Готова [новая очередь](http://localhost:8011): 60 спорных train и
42 контрольных отрывка без машинных подсказок; они ещё требуют ручной расшифровки.
[Результаты трёх режимов](reports/cockpit-training-v4/report.md) ·
[Данные и разметка](docs/cockpit_hard_v4.md).

**Предыдущий этап, 14 сентября:** исполнены два сопоставимых обучения на прежних
675 парах: обычное и с KL-штрафом к исходному Whisper, по 1200 реальных updates.
Штраф уменьшил EN WER с 7,99% до 5,44%, но baseline лучше — 3,62%. Кабинный dev
у обоих 24,35% против исходных 13,91%; RU и шумовые guards также не пройдены.
Candidate **FAIL**, независимая цель **NEEDS_MORE_DATA**, serving сохранён.
51 тест, 868 GPU ASR, 4 CPU smoke, проверка отказа при изменённом ответе и
побайтный Linux replay. [Отчёт](reports/nus-retention-v1/report.md),
[вывод](reports/nus-retention-v1/decision.md), [команды](docs/nus_retention.md).

**Предыдущий этап, 14 сентября:** с исходного Whisper обучен новый адаптер только
для декодера на 675 NUS/EN/RU парах. 187 тензоров энкодера побайтно сохранены.
После 1200 шагов цикла (1199 реальных updates из-за одного AMP skip) кабинный
dev WER **26,09%** против исходных 13,91%; чистый EN, RU и шум тоже не прошли guards.
Release **FAIL**, рабочая модель сохранена. Выполнены 40 тестов, 868 GPU-ответов,
4 CPU smoke и побайтный Linux replay. [Отчёт](reports/nus-decoder-v1/report.md),
[решение и отклонение от протокола](reports/nus-decoder-v1/decision.md),
[команды](docs/nus_decoder.md).

**Предыдущий этап:** продолжено обучение сохранённого NUS-адаптера
на 400 шагов. На своих 32 парах WER упал с 17,93% до 1,38%; на других 243 NUS
почти не изменился: 47,20% → 46,84%. На пяти человеческих кабинных dev-фрагментах
WER 26,96% против 13,91% у исходной модели; RU и шум также ухудшились.
Candidate отклонён: **FAIL**. Выполнены 868 GPU-распознаваний, CPU smoke,
16 тестов и побайтный Linux replay. [Отчёт](reports/nus-continuation-v1/report.md),
[вывод и следующий шаг](reports/nus-continuation-v1/decision.md),
[команды](docs/nus_continuation.md).

**Предыдущий этап:** EN-выборка пересобрана с двух до 19 дикторов,
одна новая LoRA обучена за 120 шагов. На пяти кабинных dev-фрагментах WER
**23,48%** против 22,61% у прежней LoRA и 13,91% у исходной модели. Целевой эффект
и шумовой guard — **FAIL**. Выполнены 675 GPU-распознаваний, 4 CPU smoke и
26 тестов; исходный serving baseline сохранён. [Отчёт](reports/balanced-v1/report.md),
[команды и ограничения](docs/balanced_retraining.md).

**Предыдущий этап:** исправлен цикл лишних проходов по хвосту в
исследовательском text-адаптере; выполнены 1056 GPU-распознаваний, 8 CPU smoke
и 25 тестов. На кабинном dev дообученная модель дала WER 20,87% против 22,61%
у своего baseline: выигрыш 7,69%, без статистического подтверждения. Проверка
точного сохранения повторённой фразы и noise guard — **FAIL**. В рабочем сервисе
сохранён обычный baseline. [Отчёт](reports/text-window-fix-v4/report.md),
[команды и ограничения](docs/text_window_fix.md).

**Предыдущие проверки, 14 сентября:** передача сохранённого EN уменьшила ошибки
small на пяти пользовательских dev-фрагментах с **34 до 16** (WER 29,57% → 13,91%).
Large-v3 при том же EN дала **20 ошибок / 17,39%**; улучшила общий RU контроль,
но ухудшила чистый EN и шум. Выполнены 1322 новых GPU вызова, CPU large smoke
и PowerShell/Linux replay. Рабочая модель сохранена, независимая приёмка не пройдена.
[Отчёт](reports/language-large-v1/report.md) ·
[Тексты ваших фрагментов](reports/language-large-v1/human-fragments.md) ·
[Команды и ограничения](docs/language_large.md).

**Предыдущий этап:** получены дополнительные BLeRIOT-B,
50 русских FLEURS dev-контролей и CVR-таблица с человеческими safety-voice labels.
Выполнено сравнение пяти ASR вариантов на 661 входе и обучение NLP на 2838 репликах.
VAD gate подавляет ложные слова на шуме; gate + denoise уменьшил ошибки на пяти
проверенных dev-фрагментах с 34 до 33 (2,94%, без статистического подтверждения).
Цель 10% не достигнута. NLP holdout macro-F1 0,5000 против 0,6449 у широких правил;
одного holdout-случая недостаточно для обобщения. Release остаётся на baseline.
[Измеренный отчёт](reports/additional-sources-v1/report.md) ·
[Данные, ограничения и проверенные команды](docs/additional_sources.md).

Из источников `SOURCES.md` скачаны BLeRIOT-A/C и шум VOICI, с проверкой
контрольных сумм. Подготовлены 67 уникальных записей и пакет из 18 фрагментов
для человеческой разметки; локальные ASR-прогоны выполнены без сети.
[Открыть разметку](http://127.0.0.1:8010) · [Инструкция и команды](docs/review_packet.md).
[Отчёт подготовки данных и dev-исполнения](reports/research-readiness-v2.md):
64 dev-прогона без ошибок; ASR/NLP quality gates — `NEEDS_MORE_DATA`.
[Поправка к gates и предыдущая проверка](docs/gate_amendment_v1.md):
220 тестов, CPU/GPU offline smoke и восстановление после сбоя прошли.
[Проверка serving baseline и экспорт отчётов](docs/reporting_v1.md): 228 тестов,
CPU/GPU offline smoke, CSV событий и измеренные графики.
[HTML dev-отчёта](reports/reporting-v1/dev-runtime/report.html) показывает реальные
времена всех 64 прогонов; WER/F1 не измерены, candidate не выбран.
На готовых издательских текстах теперь выполнен отдельный
[LoRA-эксперимент](docs/publisher_experiment.md): 40 шагов обучения, конвертация,
52 GPU-распознавания и CPU offline smoke. На 7 автоматически привязанных dev-парах
расхождений с текстом стало 57 вместо 70 (−18,57%); это **не независимая оценка WER**.
[Отчёт](reports/publisher-weak-v1/report.md) ·
[Проверка исполнения: 243 теста](reports/publisher-weak-v1/verification.json).
Качество ASR/NLP остаётся `NEEDS_MORE_DATA`, release использует прежний baseline.

После частичной проверки пользователем зафиксированы **3 train и 5 dev**
расшифровок, пересчитаны 50 сохранённых ответов. [Новый отчёт](docs/reviewed_pilot.md):
pipeline-добавки хуже baseline; A5 LoRA — 34 → 30 ошибок, но подтверждённого
статистического эффекта нет. Неразборчивые записи остаются без разметки.

Для CPU нужны Docker с Compose v2 и свободное место для образов/весов. Host Python,
Make и CUDA Toolkit на Windows не нужны. Веса и разрешённое демонстрационное аудио
получаются только явной командой; последующий worker inference работает локально.

PowerShell, из корня репозитория:

```powershell
./scripts/bootstrap.ps1
docker compose build
docker compose --profile tools run --rm tools assets fetch --preset cpu-demo
docker compose up -d
docker compose --profile tools run --rm tools doctor
docker compose --profile tools run --rm tools demo --real-asr
```

Linux:

```sh
sh scripts/bootstrap.sh
docker compose build
docker compose --profile tools run --rm tools assets fetch --preset cpu-demo
docker compose up -d
docker compose --profile tools run --rm tools doctor
docker compose --profile tools run --rm tools demo --real-asr
```

Откройте [локальную UI](http://127.0.0.1:8000) и введите `NORTH55_API_KEY` из своего
`.env`. Bootstrap сохраняет существующий `.env`, генерирует случайные секреты и не
печатает их. Ключ не хранится в localStorage. Для HTTP API передавайте `X-API-Key`;
cookie UI использует HttpOnly/SameSite и CSRF. Дополнительный annotation profile
публикует свой интерфейс только на `127.0.0.1:8010`.

GPU override заменяет существующий worker:

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
docker compose -f compose.yaml -f compose.gpu.yaml --profile tools run --rm tools demo --real-asr
# Вернуть CPU:
docker compose up -d
```

`NORTH55_GPU_ID=0` выбирает устройство; задайте другой ID только для совместимого
GPU. `NORTH55_CUDA_VISIBLE_DEVICES=0` ограничивает CUDA первым видимым устройством;
в WSL/Docker Desktop при нестандартном выборе проверьте реальную модель GPU через
doctor/runtime report. GTX 1080 Ti не поддерживается закреплённым PyTorch 2.8 CUDA
12.8; реально проверена RTX 5070 Ti. Small/float16 на CUDA — отдельная аппаратная проверка,
не доказательство улучшения по сравнению с small/int8. Для основного большого
GPU-эксперимента можно отдельно подготовить разрешённую large-v3 модель с точным
revision и проверенным локальным manifest. Автоматический `assets fetch-model`
ограничен проверенным small checkpoint; большие веса не скачивались. Обе сравниваемые
системы должны использовать одинаковые checkpoint и precision.

Проверки выполняются в контейнерах:

```sh
docker compose --profile tools run --rm --entrypoint python tools -m pytest tests/unit tests/integration -q
docker compose --profile tools run --rm --entrypoint ruff tools check src tests
docker compose --profile tools run --rm --entrypoint mypy tools src/north55_speech
docker compose --profile tools run --rm tools selftest pipeline-stages
docker compose --profile tools run --rm tools acceptance-schema
docker compose --profile tools run --rm --entrypoint python tools scripts/test_migrations.py
docker compose --profile tools run --rm --entrypoint python tools scripts/test_data_workflow.py
```

Отдельная проверка реального падения worker и недоступного брокера:

```powershell
./scripts/test-recovery.ps1
```

```sh
sh scripts/test-recovery.sh
```

Эти скрипты останавливают **только сервисы этого Compose-проекта**, поэтому запускайте
их вне обработки своих записей. Синтетические unit fixtures и LibriSpeech controls
проверяют код; они не проходят научный quality gate и не заменяют cockpit test.

Проверка inference без сети (новая папка артефактов исключает cache hit):

```powershell
$offlineRoot = '/artifacts/offline-' + [guid]::NewGuid().ToString('N')
docker run --rm --network none --env "NORTH55_ARTIFACT_ROOT=$offlineRoot" -v north55-speech_model_cache:/models:ro -v north55-speech_audio_data:/audio:ro -v north55-speech_artifact_data:/artifacts -v "${PWD}/reports:/reports" north55-speech:0.1.0 python scripts/test_offline.py
```

```sh
docker run --rm --network none -e "NORTH55_ARTIFACT_ROOT=/artifacts/offline-$(date +%s)" -v north55-speech_model_cache:/models:ro -v north55-speech_audio_data:/audio:ro -v north55-speech_artifact_data:/artifacts -v "$PWD/reports:/reports" north55-speech:0.1.0 python scripts/test_offline.py
```

Данные и аннотации:

```sh
docker compose --profile data run --rm curator datasets import-local --manifest /data/input/manifest.jsonl
docker compose --profile data run --rm curator datasets validate --manifest /data/curated/manifest.jsonl
docker compose --profile data run --rm curator datasets annotation-template --manifest /data/curated/manifest.jsonl --output /data/curated/annotations-v1.jsonl
# После реального человеческого аннотирования — новая ревизия, без перезаписи эталона:
docker compose --profile data run --rm curator datasets import-annotations --manifest /data/curated/manifest.jsonl --annotations /data/curated/annotations-v1.jsonl --output /data/curated/verified-v1.jsonl
docker compose --profile data run --rm curator benchmark prepare --config configs/datasets.yaml
```

Положите локальное audio+JSONL/CSV в `data/input`. Полная схема —
`src/north55_speech/datasets.py:Sample`; руководство — [annotation guide](docs/annotation_guide.md).
Укажите фактический manifest в `configs/datasets.yaml` перед prepare. `curator` —
минимальное дополнение к исходному CLI-контракту: импорт/разделение вынесены из tools,
чтобы dev-tools не монтировали полные или sealed test-ответы. Curator имеет доступ к
ним только для подготовки; обучение/dev используют отдельные проекции.

Обучение и исследовательский протокол:

```sh
docker compose --profile training run --rm trainer train events --config configs/events_train.yaml
docker compose --profile tools run --rm tools benchmark freeze-baseline --output /artifacts/gate-hardening-v1/baseline.lock.json
docker compose --profile tools run --rm tools benchmark dev --config configs/search.yaml
# Заполнить configs/freeze.yaml фактическим dev run и checksum из curator proof:
docker compose --profile tools run --rm tools benchmark freeze --acceptance configs/acceptance.yaml
docker compose --profile eval run --rm evaluator benchmark test --selection /artifacts/selection.lock.json
docker compose --profile tools run --rm tools benchmark report --run-id ACTUAL_RUN_ID
docker compose --profile eval run --rm evaluator promote --run-id ACTUAL_PASSING_RUN_ID
```

Первые пять команд не создают release pointer. `promote` требует всех необходимых
PASS и текущих hashes; нехватку аннотаций или неудачное улучшение обойти нельзя.
Не меняйте конфигурацию после final test: новая настройка требует нового независимого
test. Восемь trials и лимит 16 заданы в `configs/search.yaml`.

ASR-search по умолчанию оценивает ASR-этапы с rules NLP. Для полного ASR→обученный
NLP candidate после успешного `train events` задайте в `overrides` каждого
candidate trial поля `classifier: tfidf_logreg_v1` и
`classifier_artifact: events-v1` (либо фактическую версию своего артефакта).
Сделайте это **до** dev-search и freeze; baseline ASR-конфигурацию не меняйте.
Freeze проверяет веса/пороги классификатора вместе с ASR checkpoint. Без обученного
классификатора NLP gate не получит PASS, даже если ASR улучшен.

После первой полной сборки исходники можно обновить без повторного получения
зависимостей. Команды одинаковы в PowerShell и Linux; проверка `cmp` запрещает
такое обновление при изменённых pyproject.toml/uv.lock:

```sh
docker build -f scripts/Dockerfile.refresh -t north55-speech:0.1.0 .
docker compose up -d
```

При изменении зависимостей используйте полную `docker compose build`.

Опциональное ASR LoRA обучение:

```sh
docker build -f Dockerfile.train -t north55-speech-train:0.1.0 .
# После явного получения local Transformers weights с полным revision:
docker compose --profile tools run --rm tools assets fetch-snapshot --repo openai/whisper-small --revision VERIFIED_COMMIT --local-name whisper-small-transformers
docker compose -f compose.yaml -f compose.gpu.yaml --profile training run --rm trainer train asr --config configs/asr_lora.yaml
```

`VERIFIED_COMMIT` и `ACTUAL_RUN_ID` — обязательные значения из реальных manifests,
а не готовые результаты. LoRA требует разрешённых человеческих train/dev transcripts,
GPU и данных не длиннее 30 секунд с настоящим alignment. Без них команда сообщает
конкретный blocker. Test не используется для early stopping.

Для pyannote владелец сначала принимает условия community-1. Затем явно получает
полный snapshot (`assets fetch-snapshot ... --accepted-terms`, token через `HF_TOKEN`,
не аргумент командной строки) и запускает worker с `compose.diarization.yaml`.
При отсутствии весов/зависимостей ASR продолжает работать, а компонент сообщает blocked.

API: `POST /v1/sessions` (multipart `audio`, JSON `metadata`, `Idempotency-Key`),
`GET /v1/jobs/{id}`, `/cancel`, `/retry`, `GET /v1/sessions/{id}/result`, `/audio`,
`/export?format=json|csv|vtt|srt`, `POST /reviews`, `DELETE /v1/sessions/{id}`,
`GET /v1/capabilities`, `/health/live`, `/health/ready`.

Exit codes: 0 — команда выполнена/PASS; 1 — runtime error; 2 — invalid config/integrity;
3 — quality FAIL; 4 — NEEDS_MORE_DATA/INCONCLUSIVE; 5 — BLOCKED/NOT_RUN. Успешный exit
импорта или demo не означает PASS качества. Исходные SPEC/SOURCES/ACCEPTANCE сохранены.

Предыдущий выполненный опыт: [расширение по всем доступным источникам](docs/all_sources_experiment.md).
Обработаны 476 окон BLeRIOT-A/C, обучена новая LoRA на 33 слабых train-парах;
получены 1048 offline GPU ответов, включая полный VOICI и 204 шумовые смеси.
На пяти человеческих dev-расшифровках WER 29,57% → 31,30%; общий чистый контроль
остался 3,6244%, шумовой диагностический guardrail — FAIL. Статистического
подтверждения улучшения нет; quality gate NEEDS_MORE_DATA, рабочий baseline сохранён.
Сбой записи на диск восстановлен без изменения 707 готовых ответов; PostgreSQL,
RabbitMQ, API и разметка доступны. Все измерения и проверенные команды:
[отчёт](reports/all-sources-v1/report.md), [инструкция](docs/all_sources_experiment.md).

Новый выполненный запуск: [переобучение на 33 и 433 парах](docs/retraining.md).
Два LoRA-адаптера обучены по 120 шагов; выполнены 1983 offline GPU-распознавания
и отдельный CPU smoke. На пяти кабинных dev-фрагментах дополненная версия
ухудшила lexical WER с 13,91% до 22,61%; чистый общий EN улучшился с 3,62% до
3,13%, RU изменился с 9,55% до 9,88%. На шуме выросло число ложных слов.
Целевой эффект — FAIL, независимый quality gate — NEEDS_MORE_DATA;
release сохранён на baseline. [Измерения и ограничения](reports/retraining-v1/report.md).

Следующая проверка выполнена на сохранённых весах:
[декодирование и VAD](docs/decoding_diagnostics.md). Получены 1084 новых GPU-ответа
и 16 CPU smoke; оба вмешательства ухудшили кабинный dev WER. Для augmented433:
22,61% → 33,04% (`text`) и 44,35% (`vad`). VAD убрал ложные слова на выбранных
10 минутах шума, но не прошёл проверку качества речи. Все четыре варианта —
release **FAIL**; независимый quality gate **NEEDS_MORE_DATA**.
[Отчёт](reports/decoding-v1/report.md), [проверки](reports/decoding-v1/verification.json).
