# Локальное распознавание по измеренному рецепту

Результаты и границы применения: [отчёт](../reports/improvement-v1/report.md).
Это отдельный запуск для файлов, существующий API/worker остаётся прежним.
Нужны имеющиеся локальные модели, Docker Desktop с NVIDIA GPU и образ
`north55-speech-gpu:0.1.0`. Загрузка моделей в этой команде не выполняется.

Поместите файл в `data/local-audio/`, затем из корня проекта:

```sh
docker compose -f compose.improved-local.yaml run --rm transcribe --input /input/session.wav --language ru
```

Для английской записи укажите `--language en`. `auto` и `mixed` используют исходный
small; языковая маршрутизация не угадывает язык по имени файла или желаемому тексту.
Можно передать WAV/FLAC/MP3 и другие форматы, поддерживаемые FFmpeg проекта.

Новая папка в `reports/local-transcriptions/` содержит `transcript.txt`, `result.json`,
подготовленное аудио и промежуточные результаты. В JSON сохранены выбранная модель,
параметры, версия рецепта, исходные таймкоды и статус исследовательской проверки.
Исходный файл не изменяется. Тексты обрабатываются локально без сети.

Явный `--cpu` переключает вычисления на CPU/int8. Это отдельный режим: качество
основного GPU/float16 сравнения на него автоматически не переносится. Compose
сейчас всё равно запрашивает GPU; CPU-only развертывание этим файлом не обещается.

## Воспроизведение сравнения

Исторический исполнявшийся код сохранён в `reports/improvement-v1/frozen/`.
Все восемь вариантов зафиксированы до новых ASR-ответов. Для повторного подсчёта
завершённого опыта достаточно:

```sh
docker compose -f compose.improvement.yaml run --rm score
```

Команды ниже нужны только для незавершённых стадий, у которых ещё нет
`reports/improvement-v1/predictions/<system>/execution.json`:

```sh
docker compose -f compose.improvement.yaml run --rm infer infer small
docker compose -f compose.improvement.yaml run --rm infer infer small_glossary
docker compose -f compose.improvement.yaml run --rm infer infer large
docker compose -f compose.improvement.yaml run --rm infer infer large_glossary
docker compose -f compose.improvement.yaml run --rm score
```

Готовые ответы сохраняются при продолжении прерванной стадии. Завершённый inference
повторно не запускайте: это перезапишет его счётчик новых вызовов. Для проверки
сохранённого результата используется scorer выше. Полный пакет данных,
ответов и весов локальный и исключён из Git; клон репозитория сам по себе не содержит
этот пакет. Подготовка нового эксперимента требует новой директории, отдельного
протокола и проверки пересечений; существующий план не перезаписывается.
