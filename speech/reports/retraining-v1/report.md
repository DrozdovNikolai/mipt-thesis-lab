# Переобучение Whisper-small: фактические результаты

Обучение и сравнение выполнены; проверка артефактов: **PASS**. Release не изменён.

Оба адаптера обучены на RTX 5070 Ti от одного локального родителя, по 120 шагов, seed 55. Контроль: 33 слабые кабинные пары (11 мин). Дополненный: 433 пары (93,09 мин), включая 200 EN и 200 RU с издательскими текстами. Все записи были загружены; это один проход по дополненному набору и несколько по контрольному. Финальный checkpoint-120 выбран заранее; подбора по результатам этого сравнения нет.

Ниже lexical WER; для слабых эталонов это расхождение с автоматической привязкой, не доказательство качества.

| Набор | Эталонов | Слов | Исходный | 33 пары / 120 шагов | 433 пары / 120 шагов |
|---|---:|---:|---:|---:|---:|
| general_clean | 50 | 1214 | 3.62% | 3.54% | 3.13% |
| general_ru | 50 | 921 | 9.55% | 10.10% | 9.88% |
| partial_human_dev | 5 | 115 | 13.91% | 20.00% | 22.61% |
| publisher_weak_dev | 35 | 879 | 22.87% | 22.64% | 35.04% |
| voici_mix_0dB | 35 | 879 | 64.16% | 63.14% | 59.50% |
| voici_mix_10dB | 35 | 879 | 40.73% | 23.66% | 26.62% |

Вставленные слова на шуме (слов/мин; каналы учитываются отдельно):

| Набор | Минут | Исходный | Контроль | Дополненный |
|---|---:|---:|---:|---:|
| noise_only | 50.28 | 11.038 | 27.824 | 42.879 |
| bleriot_b_noise | 18.50 | 7.948 | 11.570 | 8.597 |

На пяти пользовательских dev-фрагментах:

- control: относительное снижение WER -43.75%; 95% CI разницы WER [-4.35; 10.87] п.п., 3 группы. Порог 10%: FAIL.
- augmented: относительное снижение WER -62.50%; 95% CI разницы WER [0.00; 15.22] п.п., 3 группы. Порог 10%: FAIL.

Статусы диагностик:

```json
{
  "control": {
    "cockpit_point_target": "FAIL",
    "cockpit_statistical_confirmation": "INCONCLUSIVE",
    "clean_EN_guardrail": "PASS",
    "general_RU_regression_diagnostic": "PASS",
    "noise_guardrail_diagnostic": "FAIL",
    "noise_words_per_minute_deltas": {
      "noise_only": 16.78579810105687,
      "bleriot_b_noise": 3.622517460398991
    },
    "critical_entity_nonregression": "NEEDS_MORE_DATA",
    "release_quality_gate": "NEEDS_MORE_DATA"
  },
  "augmented": {
    "cockpit_point_target": "FAIL",
    "cockpit_statistical_confirmation": "INCONCLUSIVE",
    "clean_EN_guardrail": "PASS",
    "general_RU_regression_diagnostic": "PASS",
    "noise_guardrail_diagnostic": "FAIL",
    "noise_words_per_minute_deltas": {
      "noise_only": 31.841306587431333,
      "bleriot_b_noise": 0.6488090973848939
    },
    "critical_entity_nonregression": "NEEDS_MORE_DATA",
    "release_quality_gate": "NEEDS_MORE_DATA"
  }
}
```

## Что проверено

- 1983 свежих GPU-распознавания (3 × 661); ошибки исполнения: {'parent': 0, 'control': 0, 'augmented': 0}.
- Отдельный CPU int8 smoke: EN, RU и шум. Это проверка исполнения, не сравнение точности с GPU float16.
- На CPU шумовой фрагмент дал посторонний повторяющийся текст; это сохранённый отрицательный результат. Технический PASS не оценивает его правильность.
- GPU-прогоны частично перекрывались по времени; elapsed time и device-wide memory не являются изолированным сравнением производительности.
- Фиксация кода, конфигураций, исходного checkpoint и манифестов; контроль хешей каждого входа и результата.
- Все 661 свежих ответа исходного Whisper побуквенно совпали с предыдущим small_known; входы и effective options также совпали.
- Контейнеры обучения и inference без сети; эталоны доступны только обучению train/dev и отдельному scorer.
- Сохранены сырые прогнозы, S/D/I/N, интервалы bootstrap, логи, чекпоинты и отрицательные результаты тестовых попыток.

## Ограничения

- Основной ASR gate: **NEEDS_MORE_DATA**. Имеются только 5 частично проверенных dev-фрагментов, 115 слов и 3 группы; требуются 300 независимых utterances, 3000 слов и 20 групп. Наборы уже просматривались в прошлых экспериментах.
- Критические сущности не размечены в необходимом объёме: отсутствие ухудшения не доказано. NLP и temporal gate: **NEEDS_MORE_DATA**.
- RU измерен только на общей читаемой речи. Качество RU в кабине и mixed не подтверждено. Известны только 2 EN-диктора новых train-данных; индивидуальные RU speaker IDs недоступны, разделение опирается на исходный корпус.
- Кабинные сценарии пересекаются между train/dev; группы записей и известных дикторов разделены. Для шумовых смесей один общий шумовой оригинал: CI не доказывает обобщение на независимые полёты.
- LoRA меняет checkpoint; её результат не является доказательством улучшения pipeline на неизменной ASR-модели.
- Прежние 16 dev-конфигураций сохранены; по явному запросу пользователя добавлены ровно 2 фиксированных обучения. Пороги ACCEPTANCE.yaml не изменены.

Команды воспроизведения: `docs/retraining.md`. Локальные веса находятся в Docker volume `north55-speech_model_cache`:

- `whisper-small-retraining-v1-control/{adapter,merged,checkpoints,manifest.json}` и `whisper-small-retraining-v1-control-ct2`.
- `whisper-small-retraining-v1-augmented/{adapter,merged,checkpoints,manifest.json}` и `whisper-small-retraining-v1-augmented-ct2`.
