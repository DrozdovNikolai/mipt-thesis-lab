# Исправление повторной обработки хвоста

Реализован исследовательский адаптер `src/north55_speech/text_windows.py`.
Он устраняет воспроизводимый цикл хвостовых распознаваний, сохраняя настоящее
выравнивание слов и исходные координаты. **Полная функциональная проверка FAIL:**
на удвоенной записи у второй фразы пропущено последнее слово `him`.
Исправленный text-режим не активирован в сервисе и не допущен в release.

## Что изменено

В `AsrProvider` добавлен необязательный loader; обычные вызовы по-прежнему получают
исходный faster-whisper. Проверка локальных весов вынесена в общую функцию без
изменения критериев. Общие модели не меняются через monkeypatch.

В opt-in text-адаптере локальный Silero определяет начала участков речи. Его
параметры и интервалы записываются в `backend_audit` каждого ответа. Для завершения
детектора у EOF добавляется 1 с нулевого контекста только к его входу; Whisper
получает прежний сигнал. Интервалы обрезаются до исходной длительности.

После word alignment курсор может перейти к новому началу речи после последнего
выровненного слова, с запасом 250 мс. Он не возвращается просто к акустическому
хвосту уже распознанной фразы. Начальное окно сохраняет полный контекст; следующая
обработка использует реальные координаты feature frames исходной записи.
Текстовые повторы, числа и отрицания программно не исправляются.

Изменён только блок seek-after-alignment в копии закреплённого backend loop.
Копия читаема в `src/north55_speech/vendor/faster_whisper_loop.py`; MIT-уведомление
сохранено рядом. Для неизвестной версии/хеша backend adapter сообщает ошибку.
VAD-контекст устанавливается и снимается вокруг каждого шага генератора через
ContextVar; проверено чередование двух генераторов без смешивания их аудио.

## Проверки и ограничения

- 22 теста проверяют реальный цикл backend с заменой только нейронного расчёта,
  обнаружение исходной регрессии, длинные записи, пустоту/тишину, повторённые
  токены команд, числа/отрицания, границы окон и изоляцию состояния.
- Ещё 3 теста проверяют, что нулевой контекст получает только VAD, его интервалы
  ограничены исходным временем, а некорректное аудио отклоняется. Все 25 прошли.
- На реальном исходном фрагменте 2,27 с: 9 декодирований → 1, посторонняя фраза
  `Thank you for watching` исчезла.
- Два настоящих экземпляра того же аудио с паузой 1 с дают 2 декодирования,
  но второй текст неполон. Этот FAIL не заменён более слабой проверкой.
- Для таймкодов используется искусственное размещение фрагмента с offset 30 с:
  это проверка преобразования координат, не независимая человеческая разметка.
- Модель/VAD могут терять непрерывные или тихие повторы, если новое начало речи
  не обнаружено. Отсутствие ухудшения критических команд не доказано.

В финальном опыте `reports/text-window-fix-v4` заморожены все 264 прежних входа,
same-checkpoint CUDA float16, эталоны, lexical scorer и протокол. Выполнены
1056 GPU-прогнозов: baseline/text для parent и augmented433. Старые ответы
используются только отдельно при сравнении, inference не получает эталоны,
исторические прогнозы или train. Нового обучения и final-test доступа нет.
Восемь CPU smoke завершились без runtime errors; они оценивают исполнение,
а не GPU качество. В итоговой проверке 57 проверок целостности прошли.

В `comparison.json` отдельно сравниваются исправление с прежним сломанным text
и с корректным baseline. Для целевых 10% имеет значение второе сравнение.
Пять человеческих dev-фрагментов / 115 слов / 3 группы не обеспечивают независимый
ASR gate; NLP и temporal labels не добавлялись и не подменялись правилами.

На этих dev-фрагментах parent baseline / исправление: WER 13,91% / 14,78%;
augmented baseline / исправление: 22,61% / 20,87%. Выигрыш augmented 7,69%
меньше требуемых 10%, а 95% CI включает ноль. Noise guard и release — FAIL.
[Полные измерения](../reports/text-window-fix-v4/report.md),
[статусы](../reports/text-window-fix-v4/status.json).

Checklist исполнения (замороженный протокол не перезаписан):

- [x] Исходная регрессия, настоящий повтор, пустой вход и таймкоды проверены.
- [x] Конфигурация зафиксирована до 1056 GPU-ответов и 8 CPU smoke.
- [x] Все 528 baseline-ответов совпадают с прежними текстами и таймкодами.
- [x] Resume в Linux переиспользовал 264 ответа без ASR; scorer и reporter
      после PowerShell/Linux дали байтово одинаковые результаты.
- [x] Сохранены старые результаты, эталоны и исходные требования.
- [ ] Точное сохранение повторённой фразы: FAIL, потеря `him`.
- [ ] Независимое доказательство ASR/сущностей/NLP/temporal: NEEDS_MORE_DATA.
- [ ] Release gate: FAIL, адаптер остаётся только исследовательским.

## PowerShell

Из корня проекта, с имеющимися Docker volumes аудио/моделей:

```powershell
python scripts/run_text_window_fix.py tests --study text-window-fix-v4
# Уже сохранённый FAIL по пропуску him; команда возвращает 1, результаты остаются.
python scripts/run_text_window_fix.py regression --study text-window-fix-v4
# Следующие команды — диагностика, без продвижения в release.
foreach ($textWindowSystem in @('parent_reference','parent_text','augmented_reference','augmented_text')) {
    python scripts/run_text_window_fix.py infer --study text-window-fix-v4 --system $textWindowSystem
    if ($LASTEXITCODE -ne 0) { throw "Inference failed: $textWindowSystem" }
}
python scripts/run_text_window_fix.py score --study text-window-fix-v4
python scripts/report_text_window_fix.py
```

Отдельно исполненные CPU smoke (по четыре записи на checkpoint):

```sh
python scripts/run_text_window_fix.py cpu --study text-window-fix-v4 --system parent_text
python scripts/run_text_window_fix.py cpu --study text-window-fix-v4 --system augmented_text
```

Дополнительные три проверки аудио выполнены после заморозки на том же исходном
коде, без изменения inference. Из корня репозитория, в PowerShell:

```powershell
docker run --rm --network none --entrypoint python -v "${PWD}/reports/text-window-fix-v4/frozen/src:/app/src:ro" -v "${PWD}/tests/test_text_window_audio_contract.py:/app/test_audio_contract.py:ro" -v "${PWD}/reports/text-window-fix-v4:/study" north55-speech-gpu:0.1.0 -m pytest /app/test_audio_contract.py -q --junitxml=/study/audio-contract-tests.xml
```

Повторный `infer` переиспользует успешно записанные ответы и распознаёт только
отсутствующие. Он не скрывает сохранённые runtime errors и не меняет параметры.
Для первоначальной подготовки использовались `freeze`, затем `prepare` с тем
же `--study`; повторная подготовка существующего снимка запрещена.

## Linux / WSL

```sh
python3 scripts/run_text_window_fix.py infer --study text-window-fix-v4 --system parent_text
python3 scripts/run_text_window_fix.py score --study text-window-fix-v4
python3 scripts/report_text_window_fix.py
```

На данном Windows-хосте Linux-команды исполняются через Ubuntu WSL, например:

```powershell
wsl -d Ubuntu -- python3 /mnt/c/DEV/MIPT/Diploma/Speech/scripts/run_text_window_fix.py infer --study text-window-fix-v4 --system parent_text
```

Если приватные Docker-артефакты принадлежат UID 10001, reporter читает их в
контейнере под тем же владельцем, не расширяя права на каталоги.

## Неудачные варианты сохранены

- `text-window-fix-v1`: запрет повторной обработки всего окна. Терял вторую
  настоящую фразу целиком; полный опыт 1056 GPU / 8 CPU и отрицательные gates сохранены.
- `text-window-fix-v2`: наличие любой речи после word end не отделяло хвост
  предыдущей фразы. Только механическая проверка, без quality inference.
- `text-window-fix-v3`: завершение VAD у EOF не решило это различие. Только
  механическая проверка, без quality inference.
- `text-window-fix-v4`: переход к следующему началу речи. Цикл лишних проходов
  устранён на контрольном примере; точное сохранение повторённого текста FAIL.

Консервативно учтены четыре пары прототипов: 22 → 30 конфигураций. Решения по коду
принимались по механической регрессии, без подбора по WER. Исходные пороги и
предыдущие результаты неизменны. Неуспех каждого варианта записан отдельно.
