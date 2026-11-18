# Текущий исследовательский статус

**NEEDS_MORE_DATA.** Подготовка источников и локальные ASR-прогоны проверены; научная цель не достигнута. Candidate не выбран, release не изменён.

| Работа | Implemented | Executed | Verified |
|---|---|---|---|
| A/C acquisition, hashes, полный decode, группировка 67 уникальных записей | да | да | PASS |
| Сценарии, OCR, акустические связи | да | да | машинная предварительная проверка; 2 связи требуют review |
| Пакет разметки: 18 фрагментов, 6 минут | да | да | API, аудио и экспорт PASS; 0 человеческих эталонов |
| Форма разметки в браузере | да | страница входа | INCONCLUSIVE: встроенный просмотрщик присылает Origin:null |
| ASR ablation: 8 конфигураций × 8 dev-фрагментов | да | 64 прогона | PASS исполнения; WER не оценён |
| Полные Transformers-веса и offline GPU ASR | да | да | PASS готовности весов/GPU |
| Обучение ASR LoRA / NLP на людских эталонах | да | validation отказов | NEEDS_MORE_DATA; реальное обучение NOT_RUN |
| Scored dev-search, final test и статистическое улучшение | да | NOT_RUN | NEEDS_MORE_DATA |

Все ASR ablation-прогоны используют small/int8 CPU, одинаковую языковую информацию auto и тот же набор аудио. Все 64 прогона без cache hit и runtime failure. Test и издательские сценарии в контейнер inference не монтировались.

| Конфигурация | Время на 160 с аудио, с | End-to-end RTF |
|---|---:|---:|
| A0 | 34.20 | 0.214 |
| A1 | 100.88 | 0.631 |
| A2 | 99.80 | 0.624 |
| A3 | 117.01 | 0.731 |
| A4 | 139.50 | 0.872 |
| VAD_SHORT | 133.99 | 0.837 |
| HINTS_ONLY | 31.03 | 0.194 |
| DENOISE_ONLY | 32.93 | 0.206 |

Время — измерение исполнения этого прогона; это не свидетельство улучшения распознавания. WER, confidence interval, critical entity delta, clean-control delta и NLP F1 равны null. Baseline остаётся неизменным.

Для следующего научного шага нужны подтверждённые человеком расшифровки, язык/область и отдельные event/entity/salience labels. Входные архивы и веса уже доступны. Для final test остаётся дефицит независимых данных: зарезервировано 3 группы при минимуме 20, ни один тестовый пример ещё не допущен. EN/RU/mixed технически поддержаны, подтверждённых языковых quality claims нет.

[Открыть разметку в обычном браузере](http://127.0.0.1:8010) · [Инструкция и команды](../docs/review_packet.md).

Машиночитаемый отчёт: [research-readiness-v2.json](research-readiness-v2.json). Все исходные измерения: [pending-dev-ablation.json](pending-dev-ablation.json); план: [pending-dev-ablation-plan.json](pending-dev-ablation-plan.json). Исторический data-resumption относится к первой подготовке v1 и не описывает текущие 67 записей.
