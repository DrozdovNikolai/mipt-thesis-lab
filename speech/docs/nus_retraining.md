# Обучение с NUS / Singapore Airlines VR

Последующая проверка причин ухудшения и сохранённых частей адаптера:
[диагностика NUS](nus_diagnosis.md). Исходное обучение и его измерения сохранены.

Источник скачан и технически проверен в [nus-vr-v1](../reports/nus-vr-v1/report.md).
После этой проверки пользователь явно подтвердил использование для обучения:
«можно можно обучать, делай». Подтверждение записано отдельно в
[permission.json](../reports/nus-training-v1/permission.json); публичная лицензия
авторов и разрешение на распространение весов/датасета не заявляются.

Один фиксированный опыт: [protocol.md](../reports/nus-training-v1/protocol.md).
Фактические результаты после исполнения: [report.md](../reports/nus-training-v1/report.md).

## Подготовка

Из 313 уникальных PCM-клипов отбираются 275. Исключаются все версии 11 конфликтующих
reference-групп и 29 групп с текстовыми признаками radio/address; пересечение — две группы.
Оригинальные Parquet и тексты не редактируются. Регулярное выражение зафиксировано
в `north55_speech.nus_training`; это консервативный train-фильтр, не человеческая scope-разметка.
Scope NUS остаётся `unknown`, transcript_status `weak`, primary=false.

NUS занимает одну консервативную train-группу: исходные speaker/session IDs не доказаны.
Указанный в манифесте общий session/recording ID означает группу неизвестного происхождения,
а не восстановленную реальную сессию. Таймкоды исходной длинной записи не выдумываются:
source_start/end=null. Аудио WAV извлекается из bytes без ресемплинга и с проверкой SHA256.
Пути внутри Parquet никогда не используются для чтения внешних файлов.

275 новых пар заменяют 33 прежние слабые BLeRIOT train-пары; все 400 EN/RU support
примеры и 35 dev-примеров сохраняются. Train/dev, известный human dev и диагностическое
аудио проверяются на групповые/PCM пересечения. Никакой NUS-текст не используется в prompts,
словари не расширяются, отрицания и числа не переписываются.

## Фиксированный запуск

Запускать из корня Speech в PowerShell (`python`) или Linux/Ubuntu WSL (`python3`).
Необходимы имеющиеся audio/model Docker volumes, скачанный NUS под `data/quarantine`,
предыдущие `balanced-v1` train/dev и диагностические артефакты. Одного Git-клона недостаточно.
Все driver-стадии используют локальный `north55-speech-train:publisher-v2`, scorer —
`north55-speech-gpu:0.1.0`; GPU 0 — RTX 5070 Ti. Сеть контейнерам отключена.
Первый freeze-eval не запустился из минимального GPU image из-за отсутствия PyArrow;
выбор полного runtime исправлен до inference, frozen код и протокол не менялись.
Затем обнаружилось отсутствие LD_LIBRARY_PATH для установленных cuBLAS/cuDNN:
675 неудачных GPU попыток и их FAIL-отчёт сохранены в `evaluation/`. После исправления
пути библиотек тот же frozen plan перенесён в `evaluation-v2/` с hash-аудитом.
Runner выбирает этот каталог при наличии `cuda-runtime-retry.json`; fresh run без
маркера использует `evaluation/`. Повторного обучения не было. Успешные четыре
CPU результата из первого прогона переиспользованы без новых вызовов.

```text
python scripts/run_nus_retraining.py freeze
python scripts/run_nus_retraining.py tests
python scripts/run_nus_retraining.py prepare
python scripts/run_nus_retraining.py train
python scripts/run_nus_retraining.py freeze-eval
python scripts/run_nus_retraining.py infer
python scripts/run_nus_retraining.py cpu
python scripts/run_nus_retraining.py score
python scripts/report_nus_retraining.py
```

Артефакты этого запуска уже существуют: `freeze`, `prepare`, `train`, `freeze-eval`
не предназначены для перезаписи. Полное повторное обучение требует отдельного каталога
исследования и нового имени выходной модели; не удаляйте рабочие volumes.
Повтор `infer` проверяет frozen identity и переиспользует готовые ответы, без новых ASR calls.
Сохранённая ошибка запрещает молчаливую перезапись; требуется разбор с отдельным audit.
`score` и reporter повторно вычисляют отчёты из фиксированных результатов.

Для Linux resume/пересчёта использованы те же скрипты:

```sh
python3 scripts/run_nus_retraining.py infer
python3 scripts/run_nus_retraining.py score
python3 scripts/report_nus_retraining.py
```

Веса сохраняются в существующем volume `north55-speech_model_cache`:

```text
/models/whisper-small-nus-v1/adapter
/models/whisper-small-nus-v1/merged
/models/whisper-small-nus-v1/checkpoints/checkpoint-240
/models/whisper-small-nus-v1-ct2
```

Serving pipeline автоматически не меняется. Все NUS — обучение: оценка на них не
используется как подтверждение улучшения. Сравнение на прежних dev/controls ограничено
пятью human cockpit фрагментами и не заменяет независимый quality gate.
LoRA меняет веса; даже положительный результат здесь не считается same-checkpoint
улучшением A0–A4 pipeline. Статистическая значимость, clean/noise guard и отсутствие
независимой разметки сущностей/событий отражаются раздельно.

## Исполненный checklist

- [x] Подготовлены 275 NUS + 400 support пар; 43 контрактных теста прошли.
- [x] Выполнено одно обучение на 240 шагов, все 675 примеров загружены.
- [x] Сохранены adapter/merged/CT2 и выполнен реальный GPU smoke новых весов.
- [x] Получены 675 успешных GPU-ответов и 4 CPU smoke; первоначальные CUDA ошибки сохранены.
- [x] 54 проверки артефактов прошли; Linux resume и пересчёт совпали побайтно.
- [ ] Цель WER: FAIL. Кабинный dev 13,91% → 23,48%, вставок 5 → 18 на 115 слов.
- [ ] Noise guard: FAIL; независимые ASR/entities/NLP/temporal — NEEDS_MORE_DATA.
- [ ] Release не продвинут. Рабочий small/CPU/int8 baseline сохранён.
