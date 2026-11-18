# NUS: одно выполненное переобучение Whisper-small

Проверка артефактов: **PASS** (проверок: 54). Release gate: **FAIL**. Рабочая модель сохранена.

Основание использования NUS — явное подтверждение пользователя «можно можно обучать, делай», сохранённое в [permission.json](permission.json). Публичная лицензия не обнаружена; новое разрешение авторов и право публичного распространения не заявляются.

## Данные и обучение

- 275 NUS-пар, 13.85 мин. Из 313 уникальных исключены 38: 11 конфликтов текстов и 29 текстовых признаков радиообмена, два клипа относятся к обеим причинам.
- Исходные тексты оставлены без исправлений. Все NUS — weak, scope unknown, одна train-группа; таймкоды оригинала неизвестны. Проверки scope по аудио не было; фильтр не гарантирует удаления всего ATC.
- Добавлены прежние 200 EN / 200 RU general-speech пары; всего 675 пар, 94.35 мин. 33 слабые BLeRIOT train-пары удалены только из новой смеси. Оригинальные манифесты сохранены; прежние 35 weak dev-пар совпадают побайтно.
- Исходный Transformers checkpoint, rank 8, seed 55, LR 0.00005, 240 шагов; единственный checkpoint-240 зафиксирован до обучения. Изменились данные, LR и число шагов: это один рецепт обучения, а не чистый эксперимент только с составом данных.
- GPU: NVIDIA GeForce RTX 5070 Ti; train loss 1.034404, dev loss 1.403422. Все 675 примеров загружены. Loss не является WER и не доказывает улучшение речи.
- Адаптер сохранён, слит с базой, конвертирован в CT2 float16; реальный smoke сохранённых весов выполнен.

## Lexical WER (%)

| Набор | Исходная модель | Прежняя balanced LoRA | NUS LoRA |
|---|---:|---:|---:|
| partial_human_dev | 13.91 | 23.48 | 23.48 |
| general_clean | 3.62 | 3.46 | 3.71 |
| general_ru | 9.55 | 9.77 | 8.69 |
| publisher_weak_dev | 22.87 | 34.58 | 23.32 |
| voici_mix_0dB | 64.16 | 58.82 | 55.06 |
| voici_mix_10dB | 40.73 | 26.85 | 26.73 |
| short_general_clean | 1.45 | 1.45 | 1.45 |
| quiet_general_clean | 1.45 | 1.45 | 1.45 |
| quiet_partial_human_dev | 14.78 | 28.70 | 18.26 |

Все наборы — ранее открытые dev/controls, не независимый final test. 275 обучающих NUS-клипов в эту оценку не включались. Weak publisher/mix значения означают расхождение с автоматической привязкой, а не точность относительно подтверждённого эталона.

## Кабинный dev, статистика и шум

- parent: S=10, D=1, I=5, N=115.
- balanced: S=10, D=0, I=17, N=115.
- nus: S=9, D=0, I=18, N=115.
- Относительное снижение WER против исходной модели: -68.75%. 95% cluster bootstrap CI для ΔWER: [0.00; 15.22] п.п. 2000 повторов, seed 55. Пять человеческих фрагментов, три группы; результат exploratory.

- noise_only, вставок/мин: parent=11.038; balanced=42.104; nus=13.206.
- bleriot_b_noise, вставок/мин: parent=7.948; balanced=9.083; nus=7.461.

## Gate

```json
{
  "human_dev_point_target": "FAIL",
  "clean_EN_guard": "PASS",
  "general_RU_guard": "PASS",
  "noise_guard": "FAIL",
  "runtime_guard": "PASS",
  "statistical_confirmation": "INCONCLUSIVE",
  "independent_ASR": "NEEDS_MORE_DATA",
  "critical_entities": "NEEDS_MORE_DATA",
  "release": "FAIL"
}
```

- Независимые ASR, критические сущности, NLP и temporal detection: NEEDS_MORE_DATA. Нет новых human event labels и нет подтверждённого качества RU/mixed cockpit speech.
- 675 новых GPU-ответов, 1350 исторических с проверкой hashes; одинаковые аудио, язык входа и effective decoder options, CUDA float16. Checkpoint после обучения отличается: это ASR adaptation, не same-checkpoint pipeline gain.
- Четыре CPU int8 smoke проверяют работоспособность; Linux resume переиспользовал все 675 ответов. Inference не получал эталоны, старые ответы или train-тексты. Все стадии — network none.
- Runtime failures: {"parent": 0, "balanced": 0, "nus": 0}.
- Один первоначальный freeze-eval завершился ошибкой отсутствующего PyArrow до inference. Для driver-стадий выбран имеющийся полный training image с теми же версиями ASR библиотек; код, модель, протокол и scorer сохранены. Отказ и исправление: [runtime-amendment.json](runtime-amendment.json).
- Первый полный GPU-прогон содержал 675 ошибок загрузки libcublas.so.12. Они и его FAIL-отчёт сохранены в evaluation/. После указания пути к установленным CUDA-библиотекам тот же план выполнен в evaluation-v2/. Первые четыре успешных CPU smoke переиспользованы. Обучение не повторялось, результаты не перезаписывались: [cuda-runtime-retry.json](cuda-runtime-retry.json).
- Candidate не продвинут в release. Пороги, исходные SPEC/SOURCES/ACCEPTANCE и baseline сохранены.

Команды и ограничения воспроизведения: [docs/nus_retraining.md](../../docs/nus_retraining.md).
Машинные измерения: [comparison.json](evaluation-v2/comparison.json), [status.json](status.json), [verification.json](verification.json). Побайтное сравнение пересчёта: [cross-platform-replay.json](cross-platform-replay.json).
