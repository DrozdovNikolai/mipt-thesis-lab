# NUS: диагностика и проверка исправлений

Статус исправления качества: **FAIL**. Новые варианты не продвинуты.
Проверка артефактов: **PASS**, проверок: 31.

## Что выполнено

- Записаны реальные вызовы генерации, prompt tokens, seek и выравнивание слов.
  Исходные ответы с инструментированием совпали с историческими.
- Проверены context=True/False на обеих моделях: 40 ответов для пяти human dev
  фрагментов и их тихих копий, затем 1350 ответов на всех прежних 675 dev/controls.
- Все 275 NUS train-пар распознаны исходной и полной обученной моделями: 550 ответов.
- Сохранённый адаптер разделён на encoder-only и decoder-only без новых шагов
  обучения. Проверены обе версии на 275 train и 159 controls: 868 ответов.
- Всего **2808 GPU-ответов**, **6 CPU smoke**;
  подробный runtime-статус содержится в verification/comparison, не выводится из числа вызовов.
- 22 теста проверили восстановление диагностических hooks, отсутствие
  изменения исходных tensors, точное отключение выбранного вклада LoRA и
  совместимость доказательств идентичности аудио с историческими результатами.
- Аудио, эталоны, baseline, ACCEPTANCE и пользовательские ревизии не менялись.

## Результаты lexical WER, %

| Набор | Parent | Полная NUS LoRA | Только encoder | Только decoder |
|---|---:|---:|---:|---:|
| NUS train, 275 пар (только fitting) | 63.08 | 51.50 | 59.57 | 56.88 |
| Кабинный human dev, 5 фрагментов | 13.91 | 23.48 | 147.83 | 20.87 |
| General EN, 50 фрагментов | 3.62 | 3.71 | 3.71 | 3.54 |
| General RU, 50 фрагментов | 9.55 | 8.69 | 9.55 | 8.47 |
| Тихие копии кабинного dev | 14.78 | 18.26 | 15.65 | 16.52 |

Fitting на train — измерение усвоения виденных слабых текстов, не подтверждение
качества на новых данных. Здесь одна консервативная NUS-группа. На полном NUS
адаптере улучшился 61 пример, ухудшились 14, не изменились 200; точных по lexical
scorer ответов стало 89 -> 116. Secondary canonical WER: parent
61.90% -> NUS
50.41%.
Формат чисел объясняет небольшую часть расхождения, не заменяет primary WER.

## Проверка предыдущего текста

| Набор | Parent on | Parent off | NUS on | NUS off |
|---|---:|---:|---:|---:|
| partial_human_dev | 13.91 | 17.39 | 23.48 | 23.48 |
| quiet_partial_human_dev | 14.78 | 20.87 | 18.26 | 21.74 |
| general_clean | 3.62 | 3.62 | 3.71 | 3.71 |
| general_ru | 9.55 | 9.55 | 8.69 | 8.69 |

В `reviewed-291ebb141aa4e7a7ba94ccf8d18002fb` весь повтор NUS возникает в одном
вызове генерации с нулём previous tokens. Отключение context не меняет этот
ответ. Повторная обработка хвоста/перенос prompt не объясняет именно этот случай.
Наличие повторов в аудио не установлено данным анализом: нельзя объявить текст
галлюцинацией или переписать человеческий эталон по ответу модели.

## Аудио и данные

Для всех 275 NUS проверены hashes, finite mono 16kHz, peak/RMS и локальный Silero
VAD. Нулевого сигнала и клипов без обнаруженной VAD речи: 0. Это технический
скрининг, а не подтверждение точности текстов, области речи или происхождения.
Никакие пары не удалены по несогласию ASR/VAD. Подробности сохранены локально в
fit-audit/details.json; сводка — [fit-audit/summary.json](fit-audit/summary.json).

## Gate и ограничения

```json
{
  "encoder": {
    "human_dev_point": "FAIL",
    "clean_EN": "PASS",
    "clean_RU": "PASS",
    "noise": "FAIL",
    "runtime": "PASS",
    "statistical_confirmation": "INCONCLUSIVE",
    "independent_ASR": "NEEDS_MORE_DATA",
    "critical_entities": "NEEDS_MORE_DATA",
    "release": "FAIL"
  },
  "decoder": {
    "human_dev_point": "FAIL",
    "clean_EN": "PASS",
    "clean_RU": "PASS",
    "noise": "FAIL",
    "runtime": "PASS",
    "statistical_confirmation": "INCONCLUSIVE",
    "independent_ASR": "NEEDS_MORE_DATA",
    "critical_entities": "NEEDS_MORE_DATA",
    "release": "FAIL"
  }
}
```

Все проверки используют открытый dev и train, final test не использован.
Пять human dev клипов / 115 слов / три группы не удовлетворяют ACCEPTANCE;
human critical entities, независимые NLP/temporal labels и подтверждение
качества RU/mixed cockpit speech отсутствуют. Пороги не ослаблены.
Изолированные части совместно обученного адаптера — абляция; их неудача не
доказывает, что отдельное обучение encoder всегда неработоспособно.

## Статусы и воспроизведение

Scoring потребовал отдельной [поправки совместимости](scoring-amendment.json):
у старых ответов parent нет runtime PCM hash. Их исходный file hash и параметры
сохранены; совпадение проверено через исходный файл и явно записанную
реконструкцию. Историческое измерение PCM не приписывается старому запуску.
Frozen код, слова, метрики и пороги сохранены; repair-код хранится отдельно.
Для запуска scorer по пути /repair явно установлен PYTHONPATH=/app:/app/src.
Linux resume переиспользовал 285 ответов без новых ASR-вызовов. Оба comparison
и оба файла legacy-аудита совпали побайтно с PowerShell:
[cross-platform-replay.json](cross-platform-replay.json).

Implemented: инструменты трассировки, fitting, разделения адаптера и проверки.
Executed: реальные offline GPU/CPU прогоны, scoring, технический аудит пар.
Verified: только перечисленные артефакты/контракты при PASS verification.
ML improvement: не подтверждён; release остаётся на исходном baseline.

Команды: [docs/nus_diagnosis.md](../../docs/nus_diagnosis.md).
Исходные frozen протоколы не изменялись после запуска: [diagnosis](protocol.md),
[components](../nus-lora-ablation-v1/protocol.md).
Измерения: [comparison.json](comparison.json),
[component comparison](../nus-lora-ablation-v1/comparison.json),
[verification.json](verification.json), [status.json](status.json).
