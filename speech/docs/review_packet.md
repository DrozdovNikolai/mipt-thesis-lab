# Разметка приложенных данных

Повторно скачивать или прикладывать BLeRIOT не нужно. Локально подготовлены
67 уникальных записей: 40 исходных A и 27 шумовых C. Члены одной семьи аудио
сохранены в одном split. Из 18 групп 12 относятся к train, 3 к dev, 3 к test.
Это подготовленные источники, а не автоматически допущенный benchmark.

Первый пакет содержит 18 фрагментов по 20 секунд: 10 train и 8 dev, 6 минут
в сумме. Использованы только документированные checklist-семейства; окна
30–50 и 90–110 секунд выбраны до распознавания. Test в пакет не входит.
Для каждого фрагмента сохранены исходная запись, её SHA-256, группа и
смещение таймкодов. Черновики small/int8 скрыты по умолчанию.
Теперь для 14 фрагментов также доступны предложения из готовых документов
издателя с автоматической привязкой к аудио. Для 5 прошедших проверки предложений
текст подставляется в пустое поле при открытии фрагмента. Остальные предложения
показываются с причинами неопределённости. Обновите страницу, чтобы загрузить UI.
Автоподстановка не сохраняет ревизию, не ставит флажок человеческой проверки и
не заменяет существующую разметку. Чтение подсказки фиксируется в audit trail.

Готовые тексты уже использованы для отдельного [эксперимента с LoRA](publisher_experiment.md).
Перепечатывать весь датасет для начала обучения не требуется. Человеческая
проверка нужна для независимого аудиоэталона и отсутствующих event/entity labels,
а не для повторного набора уже опубликованных сценариев.

## Открыть и проверить

Сервис уже запущен: [локальная разметка](http://127.0.0.1:8010).
Введите своё имя и значение `NORTH55_API_KEY` из локального `.env`.
Имя будет записано в ревизии. Ключ не нужно отправлять в чат.
Вход работает и во встроенном браузере. Если страница была открыта до
исправления «Неверный origin», заново откройте адрес выше и обновите страницу.
Причиной была наша политика `no-referrer`, которая обнуляла Origin при отправке
обычной HTML-формы. Она заменена на `same-origin`; проверка origin осталась строгой.
Встроенный браузер прошёл вход на изолированном тестовом пакете, а живой сервис —
HTTP-проверки входа, 18 аудиофрагментов и экспорта без записи аннотаций.
Полный ручной browser workflow разметки ещё не выдаётся за проверенный этим тестом.

Для повторного запуска, одинаково в PowerShell и Linux из корня проекта:

```sh
docker compose -f compose.yaml -f compose.annotation.yaml --profile annotation up -d --no-deps annotation
docker compose -f compose.yaml -f compose.annotation.yaml --profile annotation exec -T annotation python -m scripts.check_annotation_service --output /tmp/annotation-service.json
```

Обе команды реально выполнены через PowerShell; вторая выполняет Python внутри
Linux-контейнера. Для первоначальной сборки дополнительного образа:

```sh
docker build -f scripts/Dockerfile.annotation-tools -t north55-annotation-tools:0.1.0 .
```

Сборка выполнена. В проверенном образе Poppler 22.12.0-2+deb12u3,
Tesseract 5.3.0-2, языковые пакеты eng/fra 1:4.1.0-2. apt-зависимости этого
вспомогательного OCR-образа разрешены по репозиторию Debian на дату сборки;
для побайтового воспроизведения сохраняйте сам образ, а не полагайтесь на
будущее содержимое apt. Основные Python-зависимости закреплены в `uv.lock`.

## Что подтверждать

1. Прослушайте фрагмент целиком. Выберите область и фактически слышимый язык.
2. Введите точную расшифровку и подтвердите сверку каждого слова.
3. Выберите категории фрагмента и отдельно его значимость для разбора.
4. По возможности разметьте сущности и временные интервалы. Их подтверждение
   независимо от подтверждения текста и категорий.
5. Сохраните новую ревизию. Экспорт train/dev находится под списком фрагментов.

Проверенное отсутствие сущностей — `[]` плюс соответствующее подтверждение;
пустое поле означает, что разметки нет. У сущности обязательны `type`,
`canonical_value`, `unit`, `polarity`, `start_sec`, `end_sec`. Таймкоды в JSON
отсчитываются от начала фрагмента; интерфейс дополнительно показывает секунды
оригинала. Пример формы сущности, **не эталон какого-либо аудио**:

```json
[{"type":"speed_mention","canonical_value":150,"unit":"knot","polarity":"affirmative","start_sec":2.1,"end_sec":3.5}]
```

Не переносите числа из примера в реальные данные. Не заменяйте fifty на fifteen
по сценарию. Если слово неразборчиво, укажите интервал по
[руководству разметки](annotation_guide.md). Команда не подтверждает состояние
самолёта; роли нельзя устанавливать по голосу. Категории 20-секундного фрагмента
не доказывают качество temporal event detection на непрерывной записи.

Кнопки подсказок показывают машинный ASR и извлечённый издательский сценарий.
Они могут содержать ошибки, другой порядок или другой текст. Доступ к подсказке
фиксируется отдельно; он не делает данные `human_verified`. Сопоставление
использует только точные последовательности слов и машинные word timestamps,
не является forced alignment. Не совпавшие слова не получают выдуманных времён.
Новый отдельный `publisher_columns_and_whisper_dtw_v1` использует локальную
DTW-привязку издательского текста; её таймкоды тоже остаются машинными.

## Передать проверенные ревизии в обучение

Следующие команды выполнены с текущими данными и вернули `NEEDS_MORE_DATA`,
поскольку человеческих ревизий пока нет. Каталог обучения в этом случае
не создаётся. После разметки повторите команду; существующая версия не
перезаписывается. Экспорт допускает только EN/RU/mixed recorded-human
cockpit/read_cockpit/simulator с отдельными человеческими подтверждениями.

PowerShell, ASR:

```powershell
docker run --rm --network none --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/data/curated/annotation-packet-v1:/packet:ro" -v "${PWD}/data/curated:/curated" -v "${PWD}/reports:/reports" north55-speech:0.1.0 -m scripts.materialize_reviewed_training --packet /packet --output /curated/reviewed-asr-v1 --task asr --report /reports/reviewed-asr-readiness.json
```

Linux, ASR; та же фактически выполненная контейнерная команда, синтаксис host shell
приведён отдельно и не выдаётся за повторный прогон через Linux host:

```sh
docker run --rm --network none --entrypoint python -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data/curated/annotation-packet-v1:/packet:ro" -v "$PWD/data/curated:/curated" -v "$PWD/reports:/reports" north55-speech:0.1.0 -m scripts.materialize_reviewed_training --packet /packet --output /curated/reviewed-asr-v1 --task asr --report /reports/reviewed-asr-readiness.json
```

Для NLP замените `--task asr` на `--task events`, выход на `reviewed-events-v1`,
отчёт на `reviewed-events-readiness.json`. Этот вариант также выполнен.
Нужны категории и отдельная значимость, обе salience-класса в train и
непустой независимый dev. Машинные rules-labels не используются вместо людей.

Полученные версии подключает `compose.reviewed-training.yaml` вместо пустых
default manifests. Отсутствующий каталог не создаётся молча. Конфигурация override
проверена командой Compose `config --quiet`. Полное обучение следующими командами
ещё не исполнено, поскольку человеческих эталонов нет.

После успешного экспорта ASR, одинаково в PowerShell и Linux:

```sh
docker compose -f compose.yaml -f compose.gpu.yaml -f compose.reviewed-training.yaml --profile training run --rm trainer train asr --config configs/asr_lora.yaml
```

Для событий, PowerShell:

```powershell
$env:NORTH55_REVIEWED_DATA_VERSION = 'reviewed-events-v1'
docker compose -f compose.yaml -f compose.reviewed-training.yaml --profile training run --rm trainer train events --config configs/events_train.yaml
```

Linux:

```sh
NORTH55_REVIEWED_DATA_VERSION=reviewed-events-v1 docker compose -f compose.yaml -f compose.reviewed-training.yaml --profile training run --rm trainer train events --config configs/events_train.yaml
```

Перед следующим ASR-запуском явно выберите `reviewed-asr-v1`. Версию выходных
моделей задают `configs/asr_lora.yaml` и `configs/events_train.yaml`; повторное
обучение требует нового имени, чтобы сохранить предыдущие артефакты.
Сам факт появления manifests не означает приемлемого
качества модели или достаточного объёма обучения. И ASR, и NLP сохраняют
независимый final test и свои quality gates.

## Воспроизведение выполненных dev-прогонов

Сохранённый ниже replay использует исходный image tag до поправки scorer.
Актуальная оценка требует нового scored dev run: [поправка протокола](gate_amendment_v1.md).

План `reports/pending-dev-ablation-plan.json` фиксирует восемь конфигураций
из `configs/search.yaml` до начала прогона. Все восемь dev-фрагментов обрабатываются
каждой конфигурацией, small/int8 CPU, одинаковая языковая информация `auto`.
Ни сценарии, ни train, ни test в этот контейнер не монтируются. Ошибки сохраняются
как пустые гипотезы с operational failure; неудобные фрагменты не выбрасываются.

PowerShell, выполненная команда; повтор использует сохранённые inference records:

```powershell
docker run --rm --network none --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/data/curated/annotation-packet-v1/dev.jsonl:/dev/dev.jsonl:ro" -v "${PWD}/reports:/reports" -v north55-speech_model_cache:/models:ro -v north55-speech_audio_data:/audio:ro -v north55-speech_artifact_data:/artifacts north55-speech:asr-plan-a5578a68 -m scripts.run_pending_dev_ablation
```

Linux host syntax:

```sh
docker run --rm --network none --entrypoint python -v "$PWD/scripts:/app/scripts:ro" -v "$PWD/data/curated/annotation-packet-v1/dev.jsonl:/dev/dev.jsonl:ro" -v "$PWD/reports:/reports" -v north55-speech_model_cache:/models:ro -v north55-speech_audio_data:/audio:ro -v north55-speech_artifact_data:/artifacts north55-speech:asr-plan-a5578a68 -m scripts.run_pending_dev_ablation
```

Это вычисленные гипотезы для будущей проверки, а не завершённый scored dev-search.
Отсутствующие WER, entity delta и confidence interval остаются `null`.
Candidate не выбран, release не изменён. После появления эталонов нужен
отдельный валидируемый scored run, freeze selection и final test.

## Конкретные ограничения источников

`CVR_BEA_cvr_sp03_.wav` побайтово совпадает с DGA CVR4 reader104; оставлен
правильно именованный экземпляр. Все остальные 27 C сохранены, включая два
случая с недостаточным подтверждением акустического parent linkage. Для защиты
от leakage они консервативно объединены с предполагаемыми исходниками; качество
парного сопоставления этих двух записей пока не утверждается.

Издательские DGA CVR1/2/4/5 содержат ATC, BEA CVR — смесь кабинного и радиообмена.
Их нельзя считать cockpit по имени. DGA CVR3 содержит французскую кабинную речь,
что не подтверждает основной EN scope. Полный скрининг сохранён в
`reports/bleriot-scope-screening.json`; это документальная предварительная
проверка, а не человеческая аудиоразметка.

Три зарезервированные test-группы не удовлетворяют требованию 20 независимых
групп в `ACCEPTANCE.yaml`. Первый шестиминутный пакет позволяет начать процесс
разметки и проверить обучение, но не закрывает научную цель. Дополнительные
независимые источники/сессии и человеческие эталоны всё ещё необходимы.
