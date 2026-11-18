# Обучение на новых слабых кабинных данных

Опыт завершён: на пяти исходных частично ручных dev WER 13,04% → 16,52%,
на 35 слабых dev 21,96% → 22,07%. Расширение не дало устойчивого выигрыша;
кандидат FAIL, проверка исполнения PASS, рабочая модель сохранена.
[Результат и ограничения](../reports/cockpit-data-v7/decision.md),
[метрики](../reports/cockpit-data-v7/report.md).

Два сопоставимых обучения Whisper small с адаптерами декодера:

- `control`: 247 прежних пар и точное расписание balanced из v5;
- `expanded`: 259 пар после замены 6 полностью вложенных старых фрагментов
  18 новыми. Перекрывающихся чистых интервалов нет, новых дикторов нет.

Исходная модель и начальные адаптеры одинаковы. Оба режима выполняют 240
обновлений AdamW, по четыре примера на обновление, с 420 акустическими вариантами.
Новые пары относятся к сложным; акустические параметры и типы слотов совпадают.
Неречевой loss и KL не добавляются. Все новые тексты остаются слабыми.

Артефакты: `reports/cockpit-data-v7/`. Веса: Docker volume
`north55-speech_cockpit_data_v7`, `models/whisper-small-cockpit-data-v7-{control,expanded}`.
Рабочая модель не заменяется результатом диагностического сравнения.

Запуск из корня проекта в PowerShell, на подготовленном стенде с прежними v5/v6:

```powershell
docker compose -f compose.cockpit-data-v7.yaml run --rm prepare
docker compose -f compose.cockpit-data-v7.yaml run --rm train
Copy-Item reports/cockpit-data-v7/io-train/training.json reports/cockpit-data-v7/training.json
docker compose -f compose.cockpit-data-v7.yaml run --rm convert
Copy-Item reports/cockpit-data-v7/io-convert/conversion.json reports/cockpit-data-v7/conversion.json
$env:V7_SYSTEM = 'baseline'
docker compose -f compose.cockpit-data-v7.yaml run --rm infer infer baseline
$env:V7_SYSTEM = 'control'
docker compose -f compose.cockpit-data-v7.yaml run --rm infer infer control
$env:V7_SYSTEM = 'expanded'
docker compose -f compose.cockpit-data-v7.yaml run --rm infer infer expanded
$env:V7_SYSTEM = 'cpu-control'
docker compose -f compose.cockpit-data-v7.yaml run --rm infer infer control --cpu
$env:V7_SYSTEM = 'cpu-expanded'
docker compose -f compose.cockpit-data-v7.yaml run --rm infer infer expanded --cpu
Remove-Item Env:V7_SYSTEM
docker compose -f compose.cockpit-data-v7.yaml run --rm score
docker compose -f compose.cockpit-data-v7.yaml run --rm checks
```

Подготовка, обучение, конверсия и оценка не перезаписывают завершённые результаты.
Команды выше описывают последовательность создания нового опыта; для повторного
обучения нужны новый каталог и план. Все контейнеры работают без сети. Trainer
получает только train-метки; inference не получает эталонных текстов.

Первый train-запуск остановился до чтения данных: файл плана, созданный root,
был недоступен пользователю контейнера 10001. Владение файлами только нового
каталога v7 исправлено без изменения содержимого. Compose теперь делает это
после подготовки автоматически. Первый журнал сохранён; веса тогда не обновлялись.

Оценка охватывает 541 прежний вход v5 и 18 новых train-fit проб. Baseline на 541
входе переиспользуется с проверкой хешей; v5 balanced показан как исторический
контекст. Основное сравнение — expanded со свежим control. Закрытый test и
новые blind-dev не используются; частичные и слабые эталоны не стали независимыми.
