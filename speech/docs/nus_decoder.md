# Полный NUS + EN/RU: обучение только декодера

Один опыт [nus-decoder-v1](../reports/nus-decoder-v1/protocol.md), разрешённый
пользователем после диагностики переобучения на 32 парах. Новый адаптер начинается
с исходного Whisper-small. У энкодера нет LoRA-параметров, его веса проверяются
побайтно. Обучаются 48 decoder q/v projections, 589824 параметра LoRA.

Используется прежний полный файл `data/curated/nus-training-v1/train.jsonl`:
675 пар, 275 NUS + 200 EN + 200 RU. Тексты, права, provenance и splits сохранены.
NUS остаётся одной train-группой с неизвестными говорящими; его готовые тексты не
подменяют независимую человеческую оценку.

## Среда и бюджет

Нужны уже подготовленный image `north55-speech-train:publisher-v2`, Docker с GPU,
исходные volumes `north55-speech_model_cache`, `north55-speech_audio_data` и
локальные reports/scoring из `nus-training-v1` и `nus-lora-ablation-v1`.
В клон Git не входят сами аудио, веса и массовые ответы; без локального пакета
артефактов исторический опыт не воспроизводится.

Новые веса размещаются только в `north55-speech_nus_decoder_v1`; прежние volumes
read-only. Сеть отключена. Inference получает веса, аудио и manifests без ответов;
train получает только прежние train-тексты, scorer — эталоны после распознавания.

Один запуск: 1200 шагов цикла, batch 1 / accumulation 4, seed 55, rank 8,
alpha 16, dropout .05, FP16, TF32 off. Сохранения 240 и 1200. LR сначала линейно
спадает с 5e-5, после шага 240 равен 2e-5. Custom LambdaLR явно заменяет scheduler
из TrainingArguments. Фактические AdamW updates проверяются отдельно от счётчика
Trainer: пропуск AMP не считается выполненным обновлением и отражается как
отклонение от frozen-протокола. Данные и пороги после результата не меняются.
В `optimizer-audit.json` дополнительно сверены сохранённые optimizer checkpoints:
у прежнего joint240 и нового decoder240 по 239 реальных updates при 240 шагах
Trainer. Прежние метрики и веса этим аудитом не изменяются.

Обе точки распознают 275 NUS fit + 159 прежних controls; по два CPU smoke EN/RU
на точку. Всего 868 новых GPU-ответов и 4 CPU. Итоговая точка 1200 задана заранее.
Промежуточный checkpoint не выбирается по dev. Дополнительного release-search нет.

## PowerShell

Из корня Speech:

```powershell
python -m scripts.run_nus_decoder freeze
python -m scripts.run_nus_decoder init
python -m scripts.run_nus_decoder tests
python -m scripts.run_nus_decoder train
python -m scripts.run_nus_decoder convert
python -m scripts.run_nus_decoder fit 240
python -m scripts.run_nus_decoder fit 1200
python -m scripts.run_nus_decoder cpu 240
python -m scripts.run_nus_decoder cpu 1200
python -m scripts.run_nus_decoder transfer 240
python -m scripts.run_nus_decoder transfer 1200
python -m scripts.run_nus_decoder score-transfer
```

`freeze/init/train/convert/score-transfer` отклоняют перезапись результата.
`init` меняет владельца только указанного пустого нового volume. Повтор inference
проверяет идентичность уже успешных ответов и пишет отдельный replay audit;
отказ нельзя незаметно заменить успешным ответом.

Дополнительные проверки совместимости (32 теста, вместе с новыми 8 — 40):

```powershell
docker run --rm --network none -e PYTHONPATH=/app:/app/src -v C:/DEV/MIPT/Diploma/Speech/reports/nus-decoder-v1/frozen:/app:ro -v C:/DEV/MIPT/Diploma/Speech/reports/nus-decoder-v1/tests:/results --entrypoint python north55-speech-train:publisher-v2 -m pytest -q -p no:cacheprovider tests/test_nus_training.py tests/test_convergence.py tests/test_continuation.py --junitxml=/results/backcompat.xml
```

## Linux / WSL

Тот же launcher запускается через `python3`. Для проверки команд и возобновления:

```bash
cd /mnt/c/DEV/MIPT/Diploma/Speech
python3 -m scripts.run_nus_decoder fit 1200
```

Для отдельного пересчёта скопируйте в новый `reports/nus-decoder-v1/linux-replay`
файлы `plan.json`, `inputs.json`, каталоги `scoring`, `fit-240`, `fit-1200`,
`transfer-240`, `transfer-1200`, без готовых scoring outputs:

```bash
docker run --name north55-nus-decoder-score-linux-v1 --network none -e PYTHONPATH=/app:/app/src -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-decoder-v1/frozen:/app:ro -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-decoder-v1/linux-replay:/study -v north55-speech_audio_data:/audio:ro --entrypoint python north55-speech-train:publisher-v2 -m scripts.nus_decoder score-transfer
```

На другом хосте замените абсолютный путь. Сравните `comparison.json`,
`scored-counts.json`, `legacy-waveform-evidence.json` побайтно; фактическая проверка
фиксируется в `cross-platform-replay.json`. Это replay сохранённых ответов и
scorer, не отдельный повтор обучения.

Сводный отчёт читает измерения и frozen code, ничего не выбирая:

```powershell
$repoPath=(Get-Location).Path
docker run --name north55-nus-decoder-report-v1 --network none -e PYTHONPATH=/app:/app/src -v "${repoPath}/reports/nus-decoder-v1/frozen:/app:ro" -v "${repoPath}/scripts/report_nus_decoder.py:/presentation/report.py:ro" -v "${repoPath}/reports/nus-decoder-v1:/report" --entrypoint python north55-speech-train:publisher-v2 /presentation/report.py
```

Результаты: [report.md](../reports/nus-decoder-v1/report.md),
[comparison.json](../reports/nus-decoder-v1/comparison.json),
[summary.json](../reports/nus-decoder-v1/summary.json).
Serving переключается только через отдельную команду после необходимых gates;
данный диагностический опыт не допускает promotion.
