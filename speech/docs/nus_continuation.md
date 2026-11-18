# NUS: продолжение сохранённого обучения

Отдельный опыт [nus-continuation-v1](../reports/nus-continuation-v1/protocol.md):
400 дополнительных шагов после checkpoint 240, constant LR 2e-5, те же 32 пары.
AdamW и AMP scaler восстановлены. Исходный протокол convergence-v1 остаётся
неизменным; здесь оценка других 402 входов выполняется независимо от train WER.
Final checkpoint задан заранее. Это диагностика, не новый release dev-search.

Нужны Docker image `north55-speech-train:publisher-v2`, локальные volumes
`north55-speech_model_cache`, `north55-speech_audio_data` и
`north55-speech_nus_convergence_v1` с выполненным предыдущим опытом. Его
`reports/nus-convergence-v1` и исходный `data/curated/nus-convergence-v1/subset.jsonl`
должны присутствовать, включая локальные scoring/predictions. Клон Git без
локального пакета данных недостаточен для воспроизведения.

Для обучения используется RTX 5070 Ti (CUDA device 0), FP16, TF32 off.
Сеть отключена на всех стадиях. Исходные volumes только для чтения; новый
`north55-speech_nus_continuation_v1` хранит checkpoint/merged/CT2. Inference
не получает reference transcripts. Serving не переключается автоматически.

## PowerShell

Из корня репозитория:

```powershell
python -m scripts.run_nus_continuation freeze
python -m scripts.run_nus_continuation init
python -m scripts.run_nus_continuation tests
python -m scripts.run_nus_continuation train
python -m scripts.run_nus_continuation convert
python -m scripts.run_nus_continuation fit 160
python -m scripts.run_nus_continuation fit 400
python -m scripts.run_nus_continuation cpu 400
python -m scripts.run_nus_continuation transfer 0
python -m scripts.run_nus_continuation transfer 400
python -m scripts.run_nus_continuation score-transfer
```

Дополнительно проверены 8 тестов совместимости со старым протоколом
(в сумме 16 тестов):

```powershell
docker run --rm --network none -e PYTHONPATH=/app:/app/src -v C:/DEV/MIPT/Diploma/Speech/reports/nus-continuation-v1/frozen:/app:ro -v C:/DEV/MIPT/Diploma/Speech/reports/nus-continuation-v1/tests:/results --entrypoint python north55-speech-train:publisher-v2 -m pytest -q -p no:cacheprovider tests/test_convergence.py --junitxml=/results/backcompat.xml
```

`160` и `400` — добавленные шаги, то есть всего 400 и 640. `transfer 0` —
исходный step 240 из прежнего volume. Оба transfer используют одинаковые 402
входа. Бюджет: 400 шагов, 64 fit + 804 transfer GPU-ответа и один CPU smoke.
Оставшиеся NUS-клипы не переводятся в независимый test: говорящие неизвестны,
исходная группа общая, 52 из 243 клипов повторяют текст train-пар.

`freeze`, `init`, `train`, `convert` и scorer не предназначены для перезаписи
результата. `init` меняет владельца только явно указанного **пустого** нового
volume и отказывается работать с непустым. Успешные inference-ответы допускают
повтор с проверкой идентичности и отдельной replay-записью; отказ не затирается.

## Linux / WSL и повторный подсчёт

Тот же launcher работает через `python3 -m scripts.run_nus_continuation ...`.
Для проверки переноса команд используется Ubuntu WSL:

```bash
cd /mnt/c/DEV/MIPT/Diploma/Speech
python3 -m scripts.run_nus_continuation fit 400
```

Scorer повторяется в отдельной папке `linux-replay`, содержащей копии
`plan.json`, `inputs.json`, `scoring/`, `fit-160/`, `fit-400/`, `transfer-0/`,
`transfer-400/`, без ранее созданных `comparison.json` и
`legacy-waveform-evidence.json`. Исходники берутся из неизменного `frozen/`:

```bash
docker run --name north55-nus-continuation-score-linux-v1 --network none -e PYTHONPATH=/app:/app/src -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-continuation-v1/frozen:/app:ro -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-continuation-v1/linux-replay:/study -v north55-speech_audio_data:/audio:ro --entrypoint python north55-speech-train:publisher-v2 -m scripts.nus_continuation score-transfer
```

На другом хосте замените пути. Отдельного Linux-обучения для проверки launcher
не требуется; побайтное совпадение scoring проверяется отдельно от нового ASR.
Фактический результат replay сохраняется в `cross-platform-replay.json`.

Сводный отчёт создаётся отдельным скриптом представления уже измеренных данных:

```powershell
$repoPath=(Get-Location).Path
docker run --name north55-nus-continuation-report-v1 --network none -e PYTHONPATH=/app:/app/src -v "${repoPath}/reports/nus-continuation-v1/frozen:/app:ro" -v "${repoPath}/scripts/report_nus_continuation.py:/presentation/report.py:ro" -v "${repoPath}/reports/nus-continuation-v1:/report" --entrypoint python north55-speech-train:publisher-v2 /presentation/report.py
```

Итоги: [report.md](../reports/nus-continuation-v1/report.md),
[сырые агрегированные метрики](../reports/nus-continuation-v1/comparison.json),
[проверки исполнения](../reports/nus-continuation-v1/summary.json).
Низкий train WER не заменяет независимую приёмку и проверку критических сущностей.
