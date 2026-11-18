# NUS: воспроизводимая проверка усвоения обучающих пар

Один train-only опыт на 32 исходных парах NUS, выбранных по SHA256 аудио.
Протокол: [reports/nus-convergence-v1/protocol.md](../reports/nus-convergence-v1/protocol.md).
Результаты и ограничения: [report.md](../reports/nus-convergence-v1/report.md).

## Среда и сохранность

Используются имеющийся image `north55-speech-train:publisher-v2`, NVIDIA RTX 5070 Ti
и локальные веса Whisper-small. Сеть отключена. Исходные volumes
`north55-speech_model_cache` и `north55-speech_audio_data` смонтированы read-only.
Все новые checkpoints/merged/CT2 находятся в отдельном
`north55-speech_nus_convergence_v1`, путь внутри контейнера `/experiment`.
Ни одна версия не подключается к serving pipeline.

Inference видит frozen code, модель, аудио и manifests без ответов. Только
train-процесс получает `data/curated/nus-convergence-v1/subset.jsonl`; scorer
читает сохранённые train/dev references после генерации. Final test не используется.

## PowerShell

Из корня Speech выполнены фиксация, тесты и обучение:

```powershell
python -m scripts.run_nus_convergence freeze
python -m scripts.run_nus_convergence tests
python -m scripts.run_nus_convergence train
```

Первый `train` остановился до `trainer.train()` из-за root-владельца пустого нового
volume. Для нового пустого тома выполнено следующее ограниченное исправление:

```powershell
docker run --name north55-nus-convergence-volume-init-v1 --network none --user 0:0 -v north55-speech_nus_convergence_v1:/experiment --entrypoint python north55-speech-train:publisher-v2 -c "from pathlib import Path; import os; p=Path('/experiment').resolve(); assert str(p)=='/experiment' and p.is_dir() and not any(p.iterdir()), 'Only initialize the explicitly named empty experiment volume'; os.chown(p,10001,10001); print('Initialized empty /experiment for uid/gid 10001')"
python -m scripts.run_nus_convergence train
```

Проверка пустоты обязательна: команда не предназначена для изменения существующих
томов с данными. Первый отказ, выполненное исправление и успешный запуск сохраняются
отдельно; параметры обучения не менялись.

Дальнейшие стадии этого же протокола:

```powershell
python -m scripts.run_nus_convergence convert
python -m scripts.run_nus_convergence fit 40
python -m scripts.run_nus_convergence fit 120
python -m scripts.run_nus_convergence fit 240
python -m scripts.run_nus_convergence cpu 240
python -m scripts.run_nus_convergence score-fit
```

Только при `fit-decision.json: run_transfer=true` запускаются:

```powershell
python -m scripts.run_nus_convergence transfer 240
python -m scripts.run_nus_convergence score-transfer
```

Число шагов не подбирается по dev: сохранены 40/120/240, условие продолжения
относится исключительно к заранее выбранному последнему checkpoint 240.
Критерий WER своего train ≤10% — диагностический, не замена ACCEPTANCE.

## Повтор

`freeze`, обучение, conversion и scorer отклоняют перезапись результатов.
Повтор inference допускает только уже успешные ответы с теми же hashes и
effective options; сохраняет отдельный replay audit, новых вызовов для них нет.
Сбойные ответы нельзя незаметно переписать успешными.

Linux использует тот же Python launcher: `python3 -m scripts.run_nus_convergence ...`.
В этом опыте выполнен Ubuntu WSL-повтор:

```bash
python3 -m scripts.run_nus_convergence fit 240
```

Переиспользованы все 32 ответа, новых ASR-вызовов 0. Также выполнен `score-fit`
в отдельном `linux-replay`, куда скопированы frozen plan/inputs/scoring и три
fit-каталога без предыдущих scored outputs:

```bash
docker run --name north55-nus-convergence-score-linux-v1 --network none -e PYTHONPATH=/app:/app/src -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-convergence-v1/frozen:/app:ro -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-convergence-v1/linux-replay:/study -v north55-speech_audio_data:/audio:ro --entrypoint python north55-speech-train:publisher-v2 -m scripts.nus_convergence score-fit
```

`fit-comparison.json` и `fit-decision.json` побайтно совпали с PowerShell-результатами;
hashes записаны в `cross-platform-replay.json`. Отдельного Linux-обучения не было.
На другом Linux-хосте замените абсолютные пути к репозиторию.

Сводный отчёт создан через текущий presentation-only скрипт, который читает
зафиксированные измерения; training/scoring code при этом остаётся frozen:

```powershell
$repoPath=(Get-Location).Path
docker run --name north55-nus-convergence-report-v1 --network none -e PYTHONPATH=/app:/app/src -v "${repoPath}/reports/nus-convergence-v1/frozen:/app:ro" -v "${repoPath}/scripts/report_nus_convergence.py:/presentation/report.py:ro" -v "${repoPath}/reports/nus-convergence-v1:/report" --entrypoint python north55-speech-train:publisher-v2 /presentation/report.py
```

Выполнение по факту: `train`, `convert`, все три `fit`, `cpu`, `score-fit` выполнены.
`transfer` и `score-transfer` **не запускались**: final train WER 17.93% выше
заданного абсолютного порога 10%. Это условие диагностического запоминания,
отдельное от требования 10% относительного улучшения независимого ASR test.

Бюджет опыта: 240 optimizer steps, 96 новых GPU fit-ответов, не более 402 условных
GPU transfer-ответов, один CPU smoke. Все 32 fit-примера и остальные NUS остаются
в одной прежней train-группе; общий текст и неизвестные говорящие ограничивают
выводы о переносе даже при низком WER на оставшихся клипах.
