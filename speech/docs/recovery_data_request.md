# Следующий шаг после неудачных адаптаций

Дата проверки: 2026-09-14. Это решение по дальнейшей работе и черновик обращения;
новый корпус не получен, письмо не отправлено, новое обучение не запускалось.

## Что показали измерения

[Последний опыт](../reports/balanced-v1/report.md): исходная модель — 13,91% WER,
прежняя LoRA — 22,61%, новая — 23,48% на пяти человеческих кабинных dev-фрагментах
(115 слов, три группы). Это многократно использованный dev, не независимый test и
не оценка качества на всех разговорах в кабине. У LoRA также выросло число ложных
слов на шуме. Release gate — **FAIL**, независимое подтверждение ASR и NLP —
**NEEDS_MORE_DATA**. Рабочий baseline сохраняется.

Повторять подбор на этих пяти фрагментах оснований нет. Общеречевые пары и
автоматические гипотезы могут служить обучению, но не создают независимого эталона.
Следующий содержательный шаг — получить готовые человеческие кабинные расшифровки
с разрешением на использование и метаданными для разделения по группам.

## Конкретный источник для запроса

В [публикации DLR](https://elib.dlr.de/219140/1/650258.pdf) описаны 409 вручную
расшифрованных сегментов из 18 записей тренажёра, с немецкой и английской речью.
Для отобранных сегментов указаны WAV, проверенная расшифровка и категория ситуации;
ATC исключён. Это подходящий кандидат для проверки доступа, а не уже допущенный
датасет. На [странице публикации](https://elib.dlr.de/219140/) найдены контакты
авторов; открытая публикация сама по себе не даёт права на исходные аудиозаписи.

Ограничения: 18 записей не доказывают наличие требуемых 20 независимых групп;
английская доля неизвестна; RU не представлен; категории авторов нельзя автоматически
выдать за нашу разметку значимости, сущностей или временных событий. Даже получение
этого материала не гарантирует закрытия всех gate или улучшения WER.

## Черновик письма — не отправлен

To: sarah.ternus@dlr.de

Subject: Research access request — annotated intra-cockpit simulator speech

Dear Sarah Ternus and colleagues,

I am working on north55_speech, a local speech-processing research prototype for
crew and instructor communication inside a cockpit or simulator. The project
evaluates transcription and communication-category classification, and excludes
pilot–ATC radio communication from its primary task.

Your paper, “Automatic Speech Recognition in the Cockpit: A Comparative Study of
ASR Models for Pilot Communication” (DOI: 10.25967/650258), describes manually
transcribed simulator speech. Could you advise whether the underlying annotated
audio can be made available for research, including any application procedure,
licensing conditions, costs, and restrictions on model training and publication
of aggregate evaluation results?

We are particularly interested in:

- WAV files and existing human-verified transcripts, with English or language-span
  metadata, and the available communication-category annotations;
- pseudonymous speaker, session and source-recording identifiers, including repeat
  appearances of the same speakers, so related recordings remain in one split;
- original segment offsets and any existing entity, salience or temporal labels;
- the size of the English subset and availability of further independent sessions.

Our evaluation requires an unseen held-out set with at least 300 utterances,
3,000 reference words and 20 independent groups. We would assess whether the
available material supports this before making any quality claims. Personal
identities are not needed. Please also indicate whether your existing annotations
cover these needs or whether additional annotation would be necessary.

Thank you for your guidance.

Best regards,
[Your name and affiliation]

## Условия возобновления эксперимента

- [x] Сопоставлены результаты исходной модели и адаптаций.
- [x] Повторно проверены первичная публикация и контакт DLR; подготовлен запрос.
- [ ] Получены условия доступа и разрешённая поставка аудио с готовыми эталонами.
- [ ] Проверены происхождение, языки, качество эталонов и групповые идентификаторы;
  будущие test-ответы закрыты от обучения и выбора настроек.
- [ ] Выделены train/dev/test с учётом всех связанных speaker/session/original;
  проверен достаточный объём именно итогового test, а не всего корпуса.
- [ ] До final test заморожены гипотеза, бюджет, конфигурация и scorer; сравнение
  pipeline выполнено на одинаковых checkpoint, precision и языковой информации.
- [ ] Отдельно проверены ASR, критические сущности, NLP и временные события.

Недостающую независимую разметку должен предоставить источник или отдельный
разметчик; личная разметка пользователем не является обязательным способом.
Собственные машинные ответы не заменяют её. Если доступ получить не удастся,
сохраняются работающая инженерная часть и отрицательные экспериментальные
результаты. Исходная исследовательская цель остаётся недостигнутой; изменение
цели потребует отдельного согласования, а не изменения порогов задним числом.
