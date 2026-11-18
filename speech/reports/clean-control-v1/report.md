# Контроль чистой английской речи — A5

50 записей, 39 читателей, 7.36 мин; 100 локальных запусков, сбоев 0.

| Модель | S | D | I | N | Lexical WER |
|---|---:|---:|---:|---:|---:|
| parent | 37 | 2 | 5 | 1214 | 3.6244% |
| adapted | 37 | 2 | 5 | 1214 | 3.6244% |

Изменение WER (LoRA − parent): **+0.0000 п.п.**; допуск ACCEPTANCE: +1 п.п.
Измеренный clean-control guardrail: **PASS**. 95% paired reader-cluster bootstrap CI: [0.000000, 0.000000], 2000 повторов, seed 55.

Это отдельный A5 опыт: одна исходная Transformers модель, parent и LoRA CT2, одинаковые GPU/float16, beam=5, temperature=0, language=en. Все дополнительные стадии выключены, эталоны не передаются в inference.

Использованы готовые издательские расшифровки [LibriSpeech dev-clean](https://www.openslr.org/12/) (CC BY 4.0). Локальное независимое прослушивание не выполнено. Выборка зафиксирована по ID до чтения текстов и ответов; reader 2277 из прежних smoke tests исключён. Сохранены все 50 пар ответов, включая ошибки.

Общий ASR/NLP quality gate: **NEEDS_MORE_DATA**. Контроль аудиокниг не доказывает улучшение кабинной речи, RU/mixed, критических сущностей или temporal detection. Пересечение с исходным pretraining Whisper неизвестно. Candidate не выбран, release не изменён. На этих controls нельзя продолжать подбор LoRA.
