# Поправка к scorer до final test

Исправлены ошибки допуска результата, а не пороги приёмки. `ACCEPTANCE.yaml`,
лексический normalizer, модель и все параметры baseline сохранены. Final test
ещё не открывался. Корпусных WER/F1 и доказанного улучшения пока нет.

Причины поправки:

- `NaN` делает обычные сравнения ложными и мог приводить к ложному PASS.
  Бесконечности, строки вместо чисел, boolean вместо счётчика и значения F1
  вне 0–1 теперь отвергаются. WER выше 1 остаётся допустимым: вставок может
  быть больше, чем слов в эталоне. Отсутствующее значение не становится нулём.
- ASR gate теперь проверяет метод, seed, 2000 повторов, 95% CI, число групп,
  определение delta и порядок границ. Неполный интервал или недостаточное
  число валидных bootstrap-повторов даёт INCONCLUSIVE; неверный протокол — FAIL.
- NLP и temporal evidence ограничены замороженными языком и областью речи.
  Французские/русские данные не подтверждают EN claim. Требуются человеческая
  разметка и сведения о прослушивании. Проверенные non-speech controls остаются
  в temporal-оценке для подсчёта ложных событий. Причины недопуска аннотаций
  сохраняются; ASR-failures и `needs_review` не исключаются по результату модели.

Из основных файлов изменились только `gates.py` и `benchmark.py`. Проверка
побайтовых хешей остальных компонентов сохранена в отчёте.

| Проверка | Фактический результат |
|---|---|
| До исправления | 74 из 96 regression-проверок обнаружили неверный статус или исключение |
| Актуальный полный pytest | 220 PASS, включая 9 integration, без skipped |
| Ruff / mypy | PASS |
| CPU и GPU ASR без сети | По 4 реальных прогона, без cache hit |
| RabbitMQ недоступен при загрузке | Задание восстановлено и завершено |
| Worker завершён SIGKILL во время ASR | Задание завершено после 2 попыток |
| API, worker и annotation images | Обновлены; хеши сохранены |
| Research gates | NEEDS_MORE_DATA, candidate отсутствует |

Новый `code_hash`:
`86ab6fabd13cea229a2bdb2e526534f5c18f69f3c698191a0cccd53f6e6cf3aa`.
Новый `scorer_hash`:
`39c2bbc5b4166f0a73aed377f7d8afbed02c03fda8e78a3b840e21123484b1b3`.

Предыдущие 64 unscored dev-прогона сохранены со старым хешем и образом
`north55-speech:asr-plan-a5578a68`. Их отчёты не переименованы в результаты
нового scorer. Для текущей scored selection после разметки требуется новый
dev run и freeze. Это не использование test для настройки: test не открывался.

Повторяемые команды, выполненные через PowerShell с Linux-контейнерами;
эти же команды имеют корректный синтаксис Linux shell:

```sh
docker compose --profile tools run --rm --entrypoint python tools -m pytest tests -q --junitxml=/reports/gate-hardening/all-tests.xml
docker compose --profile tools run --rm --entrypoint sh tools -c 'ruff check src tests && mypy src/north55_speech'
docker compose --profile tools run --rm tools benchmark freeze-baseline --output /artifacts/gate-hardening-v1/baseline.lock.json
```

Отдельные новые offline-прогоны выполнялись `scripts/test_offline.py` с
`--network none`, CPU/GPU image соответственно, новым `NORTH55_ARTIFACT_ROOT`
и `NORTH55_REPORT_ROOT=/reports/gate-hardening/cpu` либо `/gpu`. Повтор с той
же папкой получит cache hit и не годится для повторной проверки uncached smoke.
Для отказоустойчивости реально выполнен `scripts/test-recovery.ps1`; перед
ним проверено отсутствие активных пользовательских заданий. Старые recovery
reports сохранены в `reports/gate-hardening/previous-recovery`.

Машиночитаемая сводка: [verification.json](../reports/gate-hardening/verification.json).
Текущий engineering gate: [engineering-gate.json](../reports/engineering-gate.json).
Первоначальный `delivery.json` и `research-readiness-v2.json` — исторические
снимки; информация о корпусах и отсутствие quality evidence остаются актуальными,
а их прежний `code_hash` не выдаётся за текущий.
