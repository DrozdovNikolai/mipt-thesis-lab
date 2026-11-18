# Выбор ответа двух ASR по аудио

Опыт завершён и отклонён: исходный частично ручной dev WER 13,04% → 21,74%,
его версии с шумом 5 dB 128,70% → 135,65%. [Результат](../reports/cockpit-selector-v8/decision.md).

Фиксированный эксперимент без новых текстовых меток и обучения. Для английского
профиля сравниваются прежние ответы Whisper small v5 balanced и Parakeet v6.
Их вероятности на исходном звуке заново вычисляет имеющийся Whisper medium.en.
При преимуществе Parakeet более 0,10 nat на токен выбирается его исходный текст.
Отдельно проверяется правило пустого ответа Parakeet. Русские контроли проходят
без изменения. Правило описано в [протоколе](../reports/cockpit-selector-v8/protocol.md).

Скоринг использует `text_token_probs`, возвращаемые CTranslate2 `Whisper.align`.
Эти вероятности зависят и от аудио, и от предшествующего текста. Они не являются
калиброванной уверенностью и могут предпочитать правдоподобные ошибки.
[Документация API](https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html).

Сохранённые ASR-ответы проверяются по хешам v5/v6. В вычисляющем выбор контейнере
нет эталонов, меток cohort или решений VAD. Пять частично ручных и 35 слабых dev
остаются прежними; их шумные версии не расширяют независимую выборку.
Новые blind-dev и закрытый test не используются.

Команды PowerShell из корня проекта на подготовленном стенде v5/v6:

```powershell
docker compose -f compose.cockpit-selector-v8.yaml run --rm prepare
$env:V8_MODE = 'gpu'
docker compose -f compose.cockpit-selector-v8.yaml run --rm infer
$env:V8_MODE = 'cpu'
docker compose -f compose.cockpit-selector-v8.yaml run --rm infer infer --cpu
$env:V8_MODE = 'replay'
docker compose -f compose.cockpit-selector-v8.yaml run --rm infer infer --replay
Remove-Item Env:V8_MODE
docker compose -f compose.cockpit-selector-v8.yaml run --rm score
docker compose -f compose.cockpit-selector-v8.yaml run --rm checks
```

Подготовка и завершённые результаты не перезаписываются. Частично завершённый
проход возобновляется с проверкой уже сохранённых записей. Новый опыт требует
нового каталога и плана. Все контейнеры работают без сети; веса уже имеются.
Прямые проходы энкодера и оценки токенов учитываются отдельно от генераций ASR:
новых гипотез этот опыт не генерирует. CPU и GPU replay выполняются на двух
заранее выбранных обучающих фрагментах, а не на новых контрольных записях.

Первый prepare остановился до создания плана: в старых входах встретилось `auto`.
Исправлено явное задание того же английского профиля, который применялся в v6
ко всем 491 входам вне русского контроля. Исходная опция языка сохранена отдельно;
веса, прежние ASR-ответы и эталоны не изменены.
