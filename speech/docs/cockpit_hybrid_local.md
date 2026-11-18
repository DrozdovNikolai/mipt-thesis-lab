# Локальный кабинный профиль с переключением по шуму

Экспериментальный английский профиль v9 сохраняет Whisper v5 balanced для
обычной речи и выбирает Parakeet при признаках сильного шума. Обучен только
небольшой классификатор шума. На прежних пяти dev исходный WER сохранился
13,04%, на их версиях с искусственным шумом 5 dB — 128,70% → 48,70%.
[Результат и ограничения](../reports/cockpit-noise-router-v9/decision.md).

Для своего файла длиной до 30 секунд, из корня проекта в PowerShell:

```powershell
$env:HYBRID_AUDIO_DIR = 'C:/Audio'
docker compose -f compose.cockpit-hybrid-local.yaml run --rm transcribe /input/recording.wav --language en --output /output/recording-result.json
Remove-Item Env:HYBRID_AUDIO_DIR
```

Замените `C:/Audio` и `recording.wav` своими путём к папке и именем файла.
Результат появится в `reports/cockpit-noise-router-v9/local-output/recording-result.json`.
Выбирайте новое имя результата для повторного запуска: существующие файлы
не перезаписываются. Можно передать несколько входных файлов перед `--output`,
модели загрузятся один раз. Длинные записи отвергаются, а не обрезаются.

Для демонстрации уже подготовленных проб:

```powershell
docker compose -f compose.cockpit-hybrid-local.yaml run --rm transcribe /input/clean.wav /input/noisy.wav /input/empty.wav /input/quiet.wav --output /output/demo-result.json
```

В JSON есть выбранный текст, модель, причина выбора, вероятность сильного
шума, контрольные суммы и таймкоды. Поле не вызванной модели имеет `null`;
оно отличается от реального пустого ASR-ответа `""`. В проверке `smoke.json`
выполнены четыре Parakeet и два Whisper вызова; все тексты и решения совпали
с сохранёнными результатами опыта.

`--language en` — английский профиль. `--language auto` оставляет английский
переключатель, но позволяет Whisper определять язык; Parakeet при этом остаётся
английской моделью. `--language ru` обходит Parakeet и использует прежний Whisper,
отдельного прироста для русского этот профиль не обещает.

Веса уже находятся локально; сеть в контейнере отключена, нужен GPU стенда.
Файлы WAV FLOAT 16 kHz сохраняют исходные отсчёты без преобразования в int16.
Другие частоты дискретизации и стерео приводятся к 16 kHz mono, поддерживаемые
остальные форматы читаются через декодер faster-whisper. Исходный файл не меняется.

Признаки, модель переключения и параметры ASR закреплены в
`reports/cockpit-noise-router-v9/local-runtime/runtime.json`, исполняемый код
сохранён рядом в `frozen/`. Создание этого пакета на стенде после завершённого v9:

```powershell
docker run --rm --network none --user 0:0 -v ${PWD}:/app -v north55-speech_cockpit_robust_v5:/robust:ro -v north55-speech_cockpit_cross_asr_v6:/cross:ro -w /app -e PYTHONPATH=/app:/app/src --entrypoint python north55-speech-train:publisher-v2 -m scripts.prepare_cockpit_hybrid_v9
```

Повторно создавать существующий пакет не нужно. Для изменения нужны новый
каталог и повторная проверка. API/worker основного приложения не переключены
на этот профиль. Качество на неизвестном реальном кабинном шуме не подтверждено;
правило пустого Parakeet уже пропустило одну речевую train-реплику.
