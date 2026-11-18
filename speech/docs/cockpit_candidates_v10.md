# Canary-Qwen и DeepFilterNet для кабинной речи

Два новых кандидата проверяются на прежнем фиксированном наборе v9. Canary-Qwen-2.5B распознаёт 491 английский вход. DeepFilterNet3 обрабатывает 56 записей, ранее выбранных акустическим переключателем как сильный шум; затем их заново распознаёт прежний Parakeet. Это новые ASR-ответы без дополнительной ручной разметки и без дообучения весов.

Материалы: [протокол](../reports/cockpit-candidates-v10/protocol.md), [план](../reports/cockpit-candidates-v10/plan.json), [таблица](../reports/cockpit-candidates-v10/report.md), [полные метрики](../reports/cockpit-candidates-v10/comparison.json), [проверка](../reports/cockpit-candidates-v10/verification.json). В плане зафиксированы SHA кода, входов, прежних решений и всех новых весов. Эталоны монтируются только в процесс подсчёта метрик.

## Воспроизведение

Образы `north55-speech-canary:v10` (NeMo 2.5) и `north55-speech-parakeet:v6` (прежний NeMo 2.4) работают без сети. Canary имеет отдельный том `north55-speech_cockpit_models_v10` с pinned весами и токенизатором. Сборка образа и загрузка публичных файлов описаны в `scripts/Dockerfile.cockpit-canary-v10` и `scripts/acquire_cockpit_models_v10.py`; журнал и SHA находятся в `reports/cockpit-models-v10/`. При загрузке исходное аудио не монтируется и не отправляется.

После подготовки нового каталога эксперимента и заморозки плана:

```powershell
docker compose -f compose.cockpit-candidates-v10.yaml run --rm canary
docker compose -f compose.cockpit-candidates-v10.yaml run --rm dfn
docker compose -f compose.cockpit-candidates-v10.yaml run --rm report score
docker compose -f compose.cockpit-candidates-v10.yaml run --rm report verify
```

Готовые execution/score/verification-файлы защищены от перезаписи. После прерывания inference разрешается продолжить только недостающие ответы с тем же планом; завершённый опыт нужно сохранять и создавать новый каталог для нового запуска. Исходные Docker volumes и локальные сырые артефакты нужны для повторного подсчёта. Один только Git не содержит многогигабайтные веса и все аудиозаписи.

## Правила кандидатов

`guarded_v9` сохраняет ответ Whisper, если Parakeet вернул пустую строку, но исходный фиксированный VAD нашёл речь. `dfn_parakeet` дополняет это правило шумоподавлением только на сильном шуме. `canary_guarded` подавляет вывод Canary только при одновременном пустом Parakeet и отрицательном VAD; `canary_router` использует Canary на несильном шуме и прежний Parakeet на сильном. Сырые результаты Canary тоже показаны, включая ложные слова на неречевых входах.

DeepFilterNet запускается заново для каждого файла, получает запас тишины для сброса задержки и возвращает исходное число отсчётов. Native writer выдаёт PCM16; это часть измеренного кандидата. Тихие и чистые контрольные входы не проходят через шумоподавление.

Критерии диагностики зафиксированы в протоколе. Пять частичных ручных и 35 слабых dev уже использовались многократно; шумные копии не расширяют число независимых дикторов. Train-метрики показываются отдельно. Даже положительный результат здесь не подтверждает независимое выполнение SPEC.

## Локальный профиль

Профиль v10 создаётся после завершения оценки и проверки; выбранный вариант записан в `reports/cockpit-candidates-v10/local-runtime/runtime.json`. Команда запускает настоящее распознавание, а не ищет сохранённый текст:

```powershell
$env:HYBRID_AUDIO_DIR='C:/Audio'
docker compose -f compose.cockpit-hybrid-v10-local.yaml run --rm transcribe /input/recording.wav --language en --output /output/recording-result.json
Remove-Item Env:HYBRID_AUDIO_DIR
```

Результат: `reports/cockpit-candidates-v10/local-runtime/output/recording-result.json`. Вход — конечный моно/стерео аудиофайл от 0,025 до 30 секунд; длинные записи не обрезаются молча. `--language ru` использует прежний Whisper; `auto` сохраняет прежнее автоматическое определение языка Whisper внутри английского маршрута. Основной API-профиль и v9 сохраняются.
