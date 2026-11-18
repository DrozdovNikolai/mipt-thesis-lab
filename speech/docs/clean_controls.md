# Проверка сохранения качества на чистой речи

После завершения доступной ручной проверки автоматически выполнен отдельный
контроль уже обученной LoRA. Результат: **50 записей / 39 читателей / 1214 слов**,
исходная модель и LoRA — **44 ошибки, lexical WER 3,6244%** каждая.
Разность равна нулю; измеренный допуск +1 п.п. из ACCEPTANCE соблюдён.
Это не доказательство требуемого улучшения кабинной речи. Общий quality gate
остаётся NEEDS_MORE_DATA, статистическое подтверждение кабинного эффекта —
INCONCLUSIVE. В рабочем приложении остаётся baseline.

| Этап | Implemented | Executed | Verified |
|---|---|---|---|
| Подготовка с проверкой архива, лицензии, аудио и freeze | да | 50 записей, 441,335 с | hashes, 16 кГц mono, без decoded duplicates |
| Parent / LoRA, GPU float16 | да | 100 ответов, 0 сбоев, сеть отключена | сохранённые ответы и effective options |
| WER и paired reader-cluster bootstrap | да | 2000 повторов, seed 55 | независимый пересчёт edit distance |
| Защита выборки и полнота оценки | да | 8 тестов | все 8 PASS |
| Независимое прослушивание этого контроля | workflow доступен | не выполнено | не заявлено |
| Полный исследовательский gate / release | да | необходимые доказательства неполны | NEEDS_MORE_DATA / без promotion |

[Отчёт](../reports/clean-control-v1/report.md),
[сырые ответы и метрики](../reports/clean-control-v1/comparison.json),
[проверка исполнения](../reports/clean-control-v1/verification.json).
Все входы заморожены в `data/curated/clean-controls-v1/plan.json` до запуска
моделей. Выбор — SHA-256 от `55:<ID>` и round-robin по читателям; тексты,
длительности и предсказания при выборе не использовались. Исключён reader 2277
из двух прежних smoke tests. Никакие неудачные ответы не заменялись.

Источник — [LibriSpeech dev-clean, OpenSLR 12](https://www.openslr.org/12/),
CC BY 4.0; attribution: Vassil Panayotov, Guoguo Chen, Daniel Povey,
Sanjeev Khudanpur. Повторно использован ранее скачанный архив. Его MD5 совпал
с [издательской контрольной суммой](https://www.openslr.org/resources/12/md5sum.txt),
SHA-256 — с provenance первоначальной загрузки. Сохранены LICENSE, README,
speaker/chapter/book metadata, исходные chapter transcripts и их hashes.
Издательские расшифровки использованы как опубликованы; новых человеческих
подтверждений не создано. Corpus admission ограничен general-control diagnostic:
локальный listening audit отсутствует, поэтому формальное release evidence не
заявлено. Данные аудиокниг не заменяют кабинный test, entity/event labels или RU/mixed.

Оба checkpoint происходят от `openai/whisper-small` revision
`973afd24965f72e36ca33b3055d56a652f456b4d`, конвертированы в CT2 float16.
У них разные проверенные model.bin; каждый из 50 ответов имеет различающийся
след confidence/timestamps. Сами строки совпали в 44 случаях, lexical edit
counts — во всех 50. Нулевой bootstrap CI разности на этой выборке не означает
доказанную эквивалентность моделей на всей речи. Время отдельных запусков сохранено,
но порядок parent → adapted и прогрев не позволяют заявлять ускорение LoRA.

В inference используются только аудио и `language=en`, beam=5, temperature=0;
VAD, hints, denoise и re-decode отключены. References читаются только при scoring.
После этого контроля запрещён подбор LoRA на тех же controls. Возможное пересечение
с исходным pretraining Whisper неизвестно. Cockpit test не открывался.

Фактически выполненные команды PowerShell из корня проекта:

```powershell
# Подготовка только один раз: при существующем наборе скрипт откажет в перезаписи.
docker run --rm --network none --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/src:/app/src:ro" -v "${PWD}/configs:/app/configs:ro" -v "${PWD}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" -v "${PWD}/data/curated:/curated" -v north55-speech_audio_data:/audio -v north55-speech_model_cache:/models:ro north55-speech:login-fix-v1 -m scripts.evaluate_clean_controls prepare --dataset /curated/clean-controls-v1

# Без --rm: состояние контейнера сохраняется как свидетельство отключённой сети.
docker run --name north55-clean-control-v1 --network none --gpus all -e CUDA_VISIBLE_DEVICES=0 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/src:/app/src:ro" -v "${PWD}/configs:/app/configs:ro" -v "${PWD}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" -v "${PWD}/data/curated/clean-controls-v1:/controls:ro" -v "${PWD}/reports:/reports" -v north55-speech_audio_data:/audio:ro -v north55-speech_model_cache:/models:ro north55-speech-gpu:0.1.0 -m scripts.evaluate_clean_controls infer

# Повторный scoring использует сохранённые ответы, нового inference нет.
docker run --rm --network none --entrypoint python -v "${PWD}/scripts:/app/scripts:ro" -v "${PWD}/src:/app/src:ro" -v "${PWD}/configs:/app/configs:ro" -v "${PWD}/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" -v "${PWD}/data/curated/clean-controls-v1:/controls:ro" -v "${PWD}/reports:/reports" -v north55-speech_audio_data:/audio:ro -v north55-speech_model_cache:/models:ro north55-speech:login-fix-v1 -m scripts.evaluate_clean_controls score
```

Для нового воспроизведения inference задайте свободное имя контейнера и другой
`--output /reports/clean-control-reproduction`. На существующем выходе скрипт
проверяет hashes и продолжает только отсутствующие записи; сохранённые ошибки
не заменяет новыми ответами. Scoring также должен получить тот же `--output`.
Данные/код/config/модели менять нельзя: проверка freeze остановит запуск.
Исходный GPU image ID и mounts записаны в `container.json`, фактические версии,
GPU и `CUDA_VISIBLE_DEVICES=0` — в `runtime.json`. GTX 1080 Ti не использовалась.

На Linux те же Docker-команды используют `$PWD` вместо `${PWD}`; перенос на
отдельный Linux host не выполнялся. Дополнительно выполнен пересчёт именно
в Linux shell внутри контейнера (`--entrypoint bash`, `-c 'python -m
scripts.evaluate_clean_controls score'`) с теми же mounts; результат совпал.
Вызов `scripts.verify_clean_controls` с теми же CPU mounts проверяет сохранённый
пакет, включая `container.json`, `container-state.json` и XML тестов.
Код возврата исследовательского `score` означает успешный расчёт; quality status
следует читать из отчёта, успешный расчёт не является release PASS.
