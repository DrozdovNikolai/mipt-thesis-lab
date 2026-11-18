# Проверка декодирования и VAD после retraining-v1

Исследование `reports/decoding-v1` проверяет две гипотезы на сохранённых весах.
`text` меняет только `without_timestamps`: обучение использовало `<|notimestamps|>`.
Слова всё равно получают реальные таймкоды выравнивания faster-whisper.
`vad` оставляет прежний декодер и отдельно проверяет интервалы Silero.
Рабочие `AsrProvider`, baseline, настройки сервиса и веса не изменяются.

Для каждого из parent и augmented433 заранее объявлены два варианта. Их сочетание
не запускается. Пользователь разрешил эти дополнительные проверки после исчерпания
прежнего бюджета: 18 + 4 = 22 конфигурации; пороги ACCEPTANCE остаются прежними.

## Данные и границы выводов

264 входа: 5 ранее размеченных кабинных dev-фрагментов, 50 EN и 50 RU общих
контролей, 35 слабых издательских привязок и по 35 их шумовых копий 0/10dB,
15 noise_only и 25 bleriot_b_noise записей (не менее пяти минут каждого вида).
Шум выбирается по SHA256, не по качеству распознавания.
Ещё 14 входов — уменьшенные на 12dB копии пяти кабинных фрагментов и девяти
общих EN реплик длительностью до четырёх секунд. Они уже входят в число 264.

Копии сохраняют group_id, оригинал, эталон и временную ось. Это диагностика
чувствительности к уровню, а не 14 новых независимых примеров. Короткие общие
реплики не выдаются за кабинные команды. Отдельной достоверной оценки распознавания
коротких критических команд нет: нужны человеческие границы/сущности.

Все входы — ранее открытые dev/diagnostic. Test не используется. Прежние 500
baseline-ответов (по 250 на модель) проверяются по хешам и сохраняются в controls.
28 ответов baseline на тихих копиях и 1056 ответов четырёх вариантов вычисляются
заново. Контейнеры inference не получают controls, эталоны и train-данные.

Интервалы VAD не склеиваются. Для слова `start_sec/end_sec` остаются координатами
исходного фрагмента; при наличии `original_start_sec` координата полной записи
равна этой величине плюс таймкод слова. Роль по голосу и состояние самолёта не
выводятся. Повторённые команды не удаляются по тексту.

## Воспроизведение

Нужны Docker, Python3 на хосте, GPU0 с CUDA и уже полученные локальные volumes
`north55-speech_audio_data`, `north55-speech_model_cache`. Весов/данных через сеть
эти команды не загружают. Используется `north55-speech-gpu:0.1.0`;
фактический image ID и mounts сохраняются в журнале запуска.

PowerShell из корня репозитория:

```powershell
# Только для нового каталога исследования; существующие снимки не перезаписывать.
.\scripts\run_decoding_diagnostics.ps1 tests
.\scripts\run_decoding_diagnostics.ps1 freeze
.\scripts\run_decoding_diagnostics.ps1 prepare
foreach ($diagnosticSystem in @('parent_baseline','augmented_baseline','parent_text','augmented_text','parent_vad','augmented_vad')) {
    .\scripts\run_decoding_diagnostics.ps1 infer -System $diagnosticSystem
    if ($LASTEXITCODE -ne 0) { throw "Failed: $diagnosticSystem" }
}
.\scripts\run_decoding_diagnostics.ps1 score
foreach ($diagnosticSystem in @('parent_text','parent_vad','augmented_text','augmented_vad')) {
    .\scripts\run_decoding_diagnostics.ps1 cpu -System $diagnosticSystem
    if ($LASTEXITCODE -ne 0) { throw "Failed: $diagnosticSystem" }
}
python scripts/report_decoding_diagnostics.py
```

Linux/WSL из того же checkout:

```sh
sh scripts/run_decoding_diagnostics.sh tests
sh scripts/run_decoding_diagnostics.sh infer --system parent_vad
sh scripts/run_decoding_diagnostics.sh score
python3 scripts/report_decoding_diagnostics.py
```

Повторный `infer` проверяет сохранённые записи и продолжает только отсутствующие.
Успешный завершённый прогон не делает новых ASR-вызовов. Запись с ошибкой не
перезаписывается незаметно. Это проверка возобновления; она не заменяет отдельные
существующие испытания восстановления очереди/worker после сбоя.

Каждый CPU smoke берёт по одному заранее определённому EN, RU, шумовому и тихому
короткому входу. CPU int8/фактический int8_float32 — только проверка исполнения,
не часть сравнения качества CUDA float16. Скорость между системами не сравнивается.

## Артефакты

- `protocol.md`, `plan.json`, `frozen/`, `frozen-files.json`: протокол и снимок кода
  до inference. Предварительный запуск подготовки, отклонённый защитой baseline,
  сохранён отдельно в `frozen-preflight-failed/`; он не делал ASR-вызовов.
- `*/predictions/`, `*/execution.json`, `*/runtime-*.json`: каждый ответ,
  выравнивание, интервалы, реальные параметры, контрольные суммы и попытки.
- `comparison.json`, `scored-counts.json`: неизменённый lexical scorer,
  S/D/I/N и bootstrap по группам. Все заранее выбранные входы учитываются.
- `verification.json`, `status.json`, `report.md`: проверка артефактов и выводы.

Статус `PASS` отдельной диагностической метрики не означает release PASS.
Число независимых кабинных эталонов, критических сущностей, NLP/event labels
остаётся недостаточным. Допустимое улучшение общего RU/EN не доказывает качество
кабинного RU/mixed. Ни один новый вариант автоматически не активируется.
