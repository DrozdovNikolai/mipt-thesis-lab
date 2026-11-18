# Балансировка, акустические искажения и обучение молчанию

Три обучения и все проверки завершены. Фиксированный кандидат: balanced-silence с прежним фильтром наличия речи.
**Диагностический статус: FAIL**. Новая независимая ручная разметка не создавалась.

Балансировка помогла на искусственно зашумлённых версиях dev, но не добавила выигрыша
на исходной речи. Обучение молчанию заметной пользы не дало; без VAD ложных слов
на шуме стало больше. [Разбор эффекта, ухудшений и ограничений](decision.md).

Все три адаптера начинают с одинаковых весов, получают по 240 настоящих обновлений; энкодер и базовые веса неизменны.
Uniform — прежние 247 пар и равномерный порядок; balanced — 960 речевых предъявлений с увеличенной долей сложных.
В balanced: 480 чистых предъявлений, 420 различных шумовых версий с отражениями/громкостью/SpecAugment, 60 парных шумовых.
Balanced-silence получает тот же речевой поток и дополнительно 240 синтетических неречевых примеров, вес loss 0.1.
Неречевые цели: настоящий токен <|nocaptions|> и EOS. Синтетические варианты не добавляют новых голосов или человеческих текстов.

## Распознавание

WER в процентах: raw / с фильтром речи. Меньше лучше.

| Набор | N | Исходная | Uniform | Balanced | Balanced + silence |
|---|---:|---:|---:|---:|---:|
| acoustic_15_partial_human_dev | 5 | 36.52 / 36.52 | 31.30 / 31.30 | 26.09 / 26.09 | 26.09 / 26.09 |
| acoustic_15_publisher_weak_dev | 35 | 34.70 / 34.70 | 45.62 / 45.62 | 31.40 / 31.40 | 31.63 / 31.63 |
| acoustic_5_partial_human_dev | 5 | 232.17 / 232.17 | 231.30 / 231.30 | 128.70 / 128.70 | 128.70 / 128.70 |
| acoustic_5_publisher_weak_dev | 35 | 89.99 / 89.99 | 62.00 / 62.00 | 57.22 / 57.22 | 57.57 / 57.57 |
| general_clean | 50 | 3.62 / 3.62 | 3.38 / 3.38 | 3.62 / 3.62 | 3.62 / 3.62 |
| general_ru | 50 | 9.55 / 9.55 | 9.12 / 9.12 | 9.01 / 9.01 | 9.34 / 9.34 |
| partial_human_dev | 5 | 13.91 / 13.91 | 13.04 / 13.04 | 13.04 / 13.04 | 13.04 / 13.04 |
| publisher_weak_dev | 35 | 22.87 / 22.87 | 21.96 / 21.96 | 21.96 / 21.96 | 21.96 / 21.96 |
| quiet_general_clean | 9 | 1.45 / 1.45 | 1.45 / 1.45 | 1.45 / 1.45 | 1.45 / 1.45 |
| quiet_partial_human_dev | 5 | 14.78 / 14.78 | 18.26 / 18.26 | 13.91 / 13.91 | 13.91 / 13.91 |
| train_hard_fit | 25 | 22.31 / 22.31 | 12.40 / 12.40 | 9.64 / 9.64 | 8.26 / 8.26 |
| train_noisy_fit | 16 | 196.06 / 96.85 | 98.43 / 91.34 | 259.84 / 92.13 | 259.84 / 92.13 |
| train_retained_fit | 206 | 6.15 / 6.15 | 5.42 / 5.42 | 5.20 / 5.20 | 5.11 / 5.11 |

## Шум и фильтр

Ложные слова в минуту: raw / с фильтром.

| Набор | Исходная | Uniform | Balanced | Balanced + silence |
|---|---:|---:|---:|---:|
| bleriot_b_noise | 4.59 / 0.00 | 4.19 / 0.00 | 4.99 / 0.00 | 5.19 / 0.00 |
| noise_only | 6.80 / 0.00 | 24.00 / 0.00 | 63.80 / 0.00 | 62.60 / 0.00 |
| synthetic_nonspeech | 11.55 / 0.00 | 5.45 / 0.00 | 8.02 / 0.00 | 8.02 / 0.00 |

Количество входов, отсечённых одинаковым VAD, по наборам:

`{"acoustic_15_partial_human_dev": 0, "acoustic_15_publisher_weak_dev": 0, "acoustic_5_partial_human_dev": 0, "acoustic_5_publisher_weak_dev": 0, "bleriot_b_noise": 25, "general_clean": 0, "general_ru": 0, "noise_only": 15, "partial_human_dev": 0, "publisher_weak_dev": 0, "quiet_general_clean": 0, "quiet_partial_human_dev": 0, "synthetic_nonspeech": 20, "train_hard_fit": 0, "train_noisy_fit": 10, "train_retained_fit": 0}`

## Проверка и ограничения

1723 новых GPU-распознаваний, 441 прежних baseline-ответов с проверкой хешей, 6 CPU-запусков.
Фактические состояния AdamW проверены в сохранённых файлах. Все 907 входных сигналов обучения и их цели воспроизведены независимо.
Фильтр фиксирован до опыта: VAD threshold 0.5, minimum speech 100 ms; при наличии речи окно сохраняется целиком.
Новые 80 акустических dev-версий наследуют прежние тексты и группы. Это испытание на искажениях, а не независимые записи.
Прежние 5 частично ручных и 35 слабых dev уже использовались многократно; групп всего 3 и 2 соответственно.
Точечные изменения и групповые интервалы сохранены в comparison.json. Train-строки измеряют подгонку к слабым текстам.
Новые 42 blind-dev и sealed test не открывались. Рабочая модель и прежние эксперименты не изменены.

Диагностические проверки: `{"uniform-raw": {"human_point": false, "human_CI": false, "general_EN": true, "general_RU": true, "noise": false, "runtime": true}, "uniform-gate": {"human_point": false, "human_CI": false, "general_EN": true, "general_RU": true, "noise": true, "runtime": true}, "balanced-raw": {"human_point": false, "human_CI": false, "general_EN": true, "general_RU": true, "noise": false, "runtime": true}, "balanced-gate": {"human_point": false, "human_CI": false, "general_EN": true, "general_RU": true, "noise": true, "runtime": true}, "balanced-silence-raw": {"human_point": false, "human_CI": false, "general_EN": true, "general_RU": true, "noise": false, "runtime": true}, "balanced-silence-gate": {"human_point": false, "human_CI": false, "general_EN": true, "general_RU": true, "noise": true, "runtime": true}}`.

## Артефакты

Протокол: protocol.md; зафиксированный код: frozen/; план: plan.json; порядок обучения: schedule.json.
Модели: Docker volume `north55-speech_cockpit_robust_v5`, каталог `models/whisper-small-cockpit-robust-v5-{uniform,balanced,balanced-silence}`.
Команды: `python -m scripts.run_cockpit_robust_v5 STAGE [ARM]`. Изменять завершённый опыт для нового обучения нельзя.
