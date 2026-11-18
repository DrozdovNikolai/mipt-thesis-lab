# Проверка обучающего тракта NUS

Работа выполняется на существующих 675 train-парах (275 NUS + 400 общих EN/RU).
Новых данных, обучения, пользовательских ревизий и доступа к test здесь нет.
Это диагностика сохранённого обучения; она не заменяет независимую оценку качества.

Протокол, assumptions и исходный checklist:
[protocol.md](../reports/nus-training-contract-v1/protocol.md).
Измерения сохраняются отдельно от прежних опытов и обслуживающей модели.

## Выполненные команды PowerShell

Из корня репозитория, с существующим локальным Docker image
`north55-speech-train:publisher-v2` и volumes аудио/моделей:

```powershell
python -m scripts.run_nus_training_contract freeze
python -m scripts.run_nus_training_contract tests
python -m scripts.run_nus_training_contract contract
python -m scripts.run_nus_training_contract contract-retry
python -m scripts.run_nus_training_contract parent
python -m scripts.run_nus_training_contract nus
```

`contract` сохраняет исходный неуспешный аудит: он ошибочно требовал побитного
совпадения FP32-слияния на CPU с результатом исходного GPU-обучения. Отдельный
`measure_nus_merge_roundoff.py` показал максимальную разницу CPU 1.49e-8 и точное
совпадение всех 72 изменённых тензоров на CUDA FP32. В `contract-retry` сохранён
повтор на исходном устройстве; требование точного совпадения не ослаблено.
Все 479 сохранённых тензоров сравниваются с заново восстановленной моделью.
Основание и hashes исправления: `contract-amendment.json` и `contract-repair/`.
Исходный код и исходный FAIL сохранены. Это исправление диагностической проверки,
а не исправление весов модели.

Первые два запуска с `freeze` и `tests` относятся к исходному зафиксированному коду.
Последующие исправления не изменяют frozen snapshot. Повтор существующей стадии
намеренно отклоняется, чтобы не перезаписывать измерения; для повторного исполнения
используйте новый каталог исследования с тем же протоколом и новым audit trail.

## Интерпретация

- Проверка входов сравнивает реальные waveform после librosa и soundfile,
  признаки WhisperProcessor/faster-whisper, язык, начало/конец последовательности
  токенов и отсутствие усечения по длине. Это техническая проверка, не прослушивание.
- Teacher forcing получает ответы только из train. Ошибка вычисляется при
  подаче правильных предыдущих токенов; это не WER самостоятельной расшифровки.
  Сравнение с чужой записью не доказывает точность каждого слова источника.
- Две генерации выполняются без монтирования расшифровок. Изменяется только
  `without_timestamps`; веса, precision, язык входа и остальные параметры сохранены.
  При этом `word_timestamps=True` оставлен, как в предыдущем опыте. Использован
  обычный faster-whisper, без ранее экспериментального исправления его цикла.
- Даже существенное улучшение WER на собственном train не допускает release.
  Для кабинного EN и отдельно RU/mixed сохраняются прежние ограничения доказательств.

Сеть во всех вычислительных контейнерах отключена. Volumes аудио/моделей доступны
только для чтения. Все предыдущие отчёты, разметка и serving pipeline сохранены.

## Пересчёт сохранённых ответов

Scorer фиксировался до новых ASR-прогонов. Вторая его версия только указывает на
аудированные результаты `contract-retry`; нормализатор и расчёт WER прежние.
После существующего `comparison.json` повтор направляется в новый output-каталог.

PowerShell (выполнено):

```powershell
$repoPath = (Get-Location).Path
docker run --name north55-nus-contract-score-v1 --network none -e PYTHONPATH=/app:/app/src -v "${repoPath}/reports/nus-training-contract-v1/frozen:/app:ro" -v "${repoPath}/reports/nus-training-contract-v1/scoring-v2:/scoring:ro" -v "${repoPath}:/work:ro" -v "${repoPath}/reports/nus-training-contract-v1:/report" --entrypoint python north55-speech-train:publisher-v2 /scoring/report_nus_training_contract.py
```

Linux/Ubuntu WSL (выполнено; каталог `linux-replay` предварительно создан):

```bash
docker run --name north55-nus-contract-score-linux-v1 --network none -e PYTHONPATH=/app:/app/src -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-training-contract-v1/frozen:/app:ro -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-training-contract-v1/scoring-v2:/scoring:ro -v /mnt/c/DEV/MIPT/Diploma/Speech:/work:ro -v /mnt/c/DEV/MIPT/Diploma/Speech/reports/nus-training-contract-v1/linux-replay:/report --entrypoint python north55-speech-train:publisher-v2 /scoring/report_nus_training_contract.py
```

На другом Linux-хосте замените абсолютный путь к репозиторию. Команды обучения
и новой ASR-генерации под Linux в этом опыте не запускались; Linux-проверка —
пересчёт тех же сохранённых ответов без новых обращений к ASR и без GPU.
