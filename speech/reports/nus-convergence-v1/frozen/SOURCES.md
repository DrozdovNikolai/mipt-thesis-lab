# Источники, проверка и ограничения

Дата проверки: 13 сентября 2026 года.

Архитектура, ontology, API, целевые thresholds и порядок разработки в SPEC.md — проектные предложения для «55 Север». Они не являются дословным воспроизведением приведённой ниже документации. Проверка документации не означает, что установлен совместимый набор библиотек, запущен Docker или выполнен ML-эксперимент.

## Исходный пользовательский материал

**U1. «План на 3 семестр.docx», предоставлен в разговоре.** Для задания использованы положения о speech-to-text, качестве авиационной терминологии, классификации эпизодов и схеме «фиксированный набор → экспертный эталон → pipeline → метрики → анализ ошибок». Файл не включён в пакет, потому что SPEC.md самостоятельно содержит необходимые требования. Пороги 10% relative WER, минимальное число групп, числовые guardrails и выбранный software stack предложены в настоящем задании, а не взяты из университетского шаблона.

## Проверенные первичные технические источники

### S1. OpenAI — Codex developer/slash commands

Проверен раздел о `/goal`: цель задаётся как `/goal <objective>`; длина objective ограничена 4000 символами, подробности предлагается выносить в файл. Поэтому команда в CODEX_GOAL.txt ссылается на SPEC.md.

```text
https://developers.openai.com/codex/cli/slash-commands
https://learn.chatgpt.com/docs/developer-commands?surface=cli
```

### S2. SYSTRAN — faster-whisper

Проверена официальная документация проекта: inference на CPU/GPU, timestamps, VAD integration, локальные модели/конвертация. Не переносить опубликованные авторами speed/memory benchmarks на собственное неизвестное железо. Совместимость CUDA/cuDNN/CTranslate2 проверять для фактически закрепляемого набора.

```text
https://github.com/SYSTRAN/faster-whisper
```

### S2a. SYSTRAN — actual transcription API

Проверено наличие параметров domain hints и особенностей обычного/batched backend в исходном коде. Полагаться на effective options установленной версии, а не на одинаково выглядящие имена аргументов.

```text
https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py
```

### S3. Silero VAD

Первичный репозиторий VAD. Закрепить revision весов и runtime; все выбранные пороги в SPEC — параметры эксперимента, не рекомендации авторов для авиации.

```text
https://github.com/snakers4/silero-vad
```

### S4. pyannote — speaker-diarization-community-1

Проверена карточка модели: локальное использование, speaker diarization, отдельные условия получения весов. Пользователь должен самостоятельно принять условия доступа; приложение не должно обходить gating и отправлять записи в облачную альтернативу без согласия.

```text
https://huggingface.co/pyannote/speaker-diarization-community-1
```

### S5. Docker — Compose GPU support

Первичная документация о GPU device reservations в Compose. Это не отменяет необходимость рабочего host driver/runtime.

```text
https://docs.docker.com/compose/how-tos/gpu-support/
```

### S6. scikit-learn — cross-validation / grouped splits

Проверены объяснения разделения train/validation/test и групповых методов оценки. Конкретные группы speaker/session/original/variant и bootstrap-протокол заданы для нашего эксперимента в SPEC.md.

```text
https://scikit-learn.org/stable/modules/cross_validation.html
```

### S7. scikit-learn — probability calibration

Первичная документация к калибровке. Не интерпретировать произвольный объединённый score как вероятность правильности ASR.

```text
https://scikit-learn.org/stable/modules/calibration.html
```

### S8. jiwer

Первичная документация инструмента WER/CER и обработки пустых references. Семантические aviation/entity metrics требуют собственного явного scorer и независимой разметки; они не появляются автоматически из jiwer.

```text
https://jitsi.github.io/jiwer/
```

### S9. Celery — tasks

Первичная документация задач, retries и acknowledgement semantics. Требования outbox/idempotency/leases в SPEC — архитектурное решение проекта, а не автоматическая гарантия Celery.

```text
https://docs.celeryq.dev/en/stable/userguide/tasks.html
```

### S10. Hugging Face PEFT — ASR adaptation example

Проверен официальный guide для PEFT/ASR на ветке main. Это отправная точка реализации optional fine-tuning, не гарантированно совместимая с любым релизом готовая команда. Разработчик обязан закрепить и проверить свои версии, сохранение и последующую загрузку/конвертацию весов.

```text
https://huggingface.co/docs/peft/main/en/task_guides/int8-asr
```

### S11. scikit-learn — текстовые признаки и multi-label estimator

Проверены первичные API-документы для TF-IDF и OneVsRestClassifier. Выбор линейной модели, labels и thresholds — предложение для первой версии проекта.

```text
https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html
https://scikit-learn.org/stable/modules/generated/sklearn.multiclass.OneVsRestClassifier.html
```

## Датасеты: что ещё необходимо подтвердить

**Ни один аудиокорпус в рамках подготовки этого пакета не скачивался целиком, не прослушивался и не проходил проверку transcript alignment.** Поэтому приведённые далее записи — список кандидатов из обсуждения, а не заверение о готовом доступе или об отсутствии ATC во всех файлах.

Для BLeRIOT-A в текущем поиске обнаружено название публикации в Recherche Data Gouv, но прямое чтение соответствующих dataset/API страниц не удалось. Для BLeRIOT-C надёжно проверить содержимое записи в этой сессии также не удалось. Это ограничение проверки, а не доказательство отсутствия корпусов. Не переносить предыдущие утверждения о часах, лицензиях, файлах или A/C correspondence в код без проверки.

| Кандидат | Планируемая роль | Текущий статус в задании |
|---|---|---|
| BLeRIOT-A | Возможный speech corpus cockpit-oriented материала | VERIFY_REQUIRED: WAV, transcripts, license, speakers, scope |
| BLeRIOT-C | Возможный degraded/cockpit-like speech test | VERIFY_REQUIRED: существующая версия, разметка, точная связь с A |
| HIWIRE | Возможный корпус cockpit-команд | Каталожное название найдено; фактическая поставка/условия/стоимость/формат не проверены |
| VOICI, Zenodo 2660112 | Возможный источник cockpit noise для augmentation | Поиском подтверждено название noise-публикации; состав аудио и условия требуют проверки |
| NLPVladimir/aviation-command-dataset-ru | Дополнительный RU command test | Происхождение, лицензия и реальный/синтетический характер НЕ подтверждены в этом пакете |
| IEM/DLR pilot speech, упомянутые ранее | Возможные будущие реальные simulator holdouts | Доступ к WAV/эталонам не установлен; не обязательная зависимость |
| CVR text-only материалы | Потенциальный NLP-источник | Не ASR benchmark; нужны права, cockpit filtering и независимые подходящие labels |

Discovery identifiers из предыдущего обсуждения, **не валидированные download URLs**:

```text
BLeRIOT-A:
https://entrepot.recherche.data.gouv.fr/dataset.xhtml?persistentId=doi%3A10.57745%2FEWXJLT

BLeRIOT-C:
https://entrepot.recherche.data.gouv.fr/dataset.xhtml?persistentId=doi%3A10.57745%2FASYVFP

HIWIRE discovery:
https://live.european-language-grid.eu/catalogue/corpus/2059

VOICI discovery:
https://zenodo.org/records/2660112

RU aviation commands discovery:
https://huggingface.co/datasets/NLPVladimir/aviation-command-dataset-ru

IEM report discovery:
https://iem.kug.ac.at/fileadmin/03_Microsites/01_Kuenstlerisch_wissenschaftliche_Einheiten/01_Institute/Institut_17_Elektronische_Musik_und_Akustik/Projekte/2011/report45_11.pdf

DLR paper discovery:
https://elib.dlr.de/214890/
```

UWB-ATCC, ATCO2, ATCOSIM и смесь ATC-ASR не использовать как основной набор этого проекта: пользователь явно исключил ATC-задачу. Общеречевые корпуса допустимы как отдельно обозначенные технические controls, но не как доказательство улучшения именно cockpit speech.

## Минимальная процедура допуска источника

Зафиксировать лицензию/условия и право использования. Проверить реальную выдачу файлов и content hashes. Прослушать репрезентативные фрагменты и сверить человеческие transcripts. Установить scope, языки, происхождение речи, наличие speaker/session/variant IDs и независимость предполагаемого test. Только после этого писать адаптер фактического формата и включать корпус в замороженный протокол.

Если источник недоступен, сохранить точную ошибку/ограничение, реализовать local-import workflow и указать, какие файлы/annotations нужны. Не придумывать архивы, metadata fields, экспертов или результаты.
