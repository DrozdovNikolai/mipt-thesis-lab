"""Render measured expanded-source results with their distinct reference limitations."""

import json
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from north55_speech.core import atomic_json, file_hash, settings


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    root = Path('/reports/all-sources-v1')
    result = read(root / 'evaluation/comparison.json')
    interruption = read(root / 'resumption/attempt-1.json')
    preparation = read(Path('/expanded/preparation-report.json'))
    plan = read(Path('/expanded/plan.json'))
    training_root = settings.model_root / 'whisper-small-publisher-expanded-v1'
    training, history = read(training_root / 'manifest.json'), read(training_root / 'training-history.json')
    atomic_json(root / 'training-manifest.json', training)
    atomic_json(root / 'training-history.json', history)
    atomic_json(root / 'expanded-preparation.json', preparation)
    labels = {'publisher_weak_dev': 'BLeRIOT: слабая издательская привязка',
              'partial_human_dev': 'Сохранённые человеческие dev-расшифровки',
              'general_clean': 'LibriSpeech: общий чистый контроль',
              'voici_mix_0dB': 'BLeRIOT + VOICI, 0 dB (слабые эталоны)',
              'voici_mix_10dB': 'BLeRIOT + VOICI, 10 dB (слабые эталоны)'}
    lines = ['# Расширенный опыт на доступных источниках', '',
             f"Обработано **{preparation['total_rows']} окон BLeRIOT-A/C** по 20 секунд, "
             f"{preparation['groups']['split_groups']['train']} исходных train-групп и {preparation['groups']['split_groups']['dev']} dev-группы.",
             f"Строгие условия привязки допустили **{preparation['eligible_train']} train / {preparation['eligible_dev']} dev** слабых пар. "
             'Пороги чисел, anchors и alignment не ослаблялись. В новом опыте дополнительно отклонён любой язык, который alignment-модель не определила как EN.', '',
             'Рассмотрены все полные окна документированных английских checklist-семейств, включая TBM940. '
             'TBM940 не прошёл автоматические условия допуска в обучение; это обработанный источник, а не подтверждённые учебные пары. '
             'Конечные хвосты короче 20 секунд перечислены в плане как отложенные. CVR/ATC, французские и неизвестные сценарии в эту EN адаптацию не входят.', '',
             f"**Обучение исполнено:** 40 optimizer steps, rank 8, lr=0.0001, seed 55; "
             f"{training['train_metrics']['train_runtime']:.3f} с на {training['gpu']}. "
             'Adapter, merged weights и CT2 conversion сохранены. Родитель — тот же pinned openai/whisper-small. '
             'Новый checkpoint получен с нуля от родителя; старый checkpoint не перезаписан.', '',
             f"**Сравнение исполнено:** {result['runs']} локальных GPU/float16 распознаваний, "
             f"сбоев исполнения ASR в итоговых записях **{result['runtime_failures']}**. Настройки обеих моделей совпадают; beam=5, temperature=0, "
             'дополнительные ASR стадии отключены. Подготовка смесей использует VAD только для определения SNR, не для обрезки входа ASR.', '',
             f"**Восстановление:** один реальный сбой записи на диск (OSError, Errno 5) прервал опыт после "
             f"{interruption['prior_completed_predictions']} сохранённых ответов. По тому же замороженному плану исполнены "
             f"оставшиеся {interruption['missing_prediction_count']} распознавания. Проверка SHA-256 подтверждает сохранность прежних ответов. "
             'Несохранённый ответ прерванного вызова недоступен; он не выдан за успешное измерение. '
             '[Состояние и hashes до восстановления](resumption/attempt-1.json), '
             '[исходная ошибка](resumption/interrupted-tail.log). Нулевое число итоговых сбоев исполнения ASR не означает отсутствие инфраструктурного сбоя или ошибок распознанного текста.', '',
             '| Набор | Всего / с эталоном | Parent: ошибки / слова | Новая LoRA: ошибки / слова | WER до → после |',
             '|---|---:|---:|---:|---:|']
    for name, label in labels.items():
        c = result['cohorts'][name]
        a, b = c['scores']['parent'], c['scores']['expanded']
        ae, be = a['S'] + a['D'] + a['I'], b['S'] + b['D'] + b['I']
        lines.append(f"| {label} | {c['samples']} / {c['scored']} | {ae} / {a['N']} | {be} / {b['N']} | "
                     f"{a['wer_lexical_corpus']:.2%} → {b['wer_lexical_corpus']:.2%} |")
    lines += ['', 'WER для автоматически привязанных сценариев и их смесей — **proxy несоответствия слабому тексту**. '
              'Оценены все объявленные подходящие эталоны; остальные ответы тоже сохранены, но отсутствующий эталон не превращён в нулевую ошибку.', '']
    for name in ('publisher_weak_dev', 'partial_human_dev'):
        c = result['cohorts'][name]
        ci = c['bootstrap']
        relative = c['relative_reduction']
        target = relative is not None and relative >= .10
        significant = ci['upper'] is not None and ci['upper'] < 0
        diagnostic = 'POINT_AND_CI_MET_ON_NONFINAL_SUBSET' if target and significant else ('INCONCLUSIVE' if target else 'FAIL_POINT_TARGET')
        lines.append(f"{labels[name]}: относительное снижение {relative:.2%}; "
                     f"paired cluster bootstrap CI для «новая − parent»: [{ci['lower']:.6f}; {ci['upper']:.6f}], "
                     f"{ci['independent_groups']} группы, seed 55, 2000 повторов. Диагностический вывод: **{diagnostic}**.")
    noise = result['cohorts']['noise_only']
    rates = noise['inserted_words_per_minute']
    lines += ['', f"**VOICI без добавленной речи:** весь исходник, {noise['duration_minutes']:.4f} минут / {noise['samples']} окон; "
              f"слов в минуту по пустому эталону издателя: parent **{rates['parent']:.4f}**, новая LoRA **{rates['expanded']:.4f}**.",
              f"Измеренные ограничения: clean **{result['diagnostic_guardrails']['clean']}**; "
              f"noise **{result['diagnostic_guardrails']['noise_under_publisher_assumption']}**.", '',
              'Издатель сообщил об удалении речи из VOICI, но независимое локальное прослушивание отсутствует. '
              'Вся шумовая запись назначена только в dev. Во всех смесях один и тот же исходный шум: '
              'это одна noise-группа, а не множество независимых полётов. Слабый текст чистой записи не подтверждает разборчивость шумовой смеси. '
              'Bootstrap для смесей с одной группой вырожден (одинаковые границы); он не подтверждает статистическую значимость улучшения. '
              'Нормальный training augmentation по-прежнему требует проверенного noise scope; диагностические смеси в обучение не переданы.', '',
              'Чистые LibriSpeech controls и пять пользовательских dev-расшифровок уже просматривались ранее. '
              'Они служат регрессионной проверкой; на них не выбирается release. В человеческом поднаборе сохранены '
              'подсказки в истории разметки и неуточнённая запись чисел цифрами. Критические сущности и события не размечались машиной под видом человека.', '',
              '**ASR/NLP/temporal quality gates: NEEDS_MORE_DATA. Candidate не выбран, release не изменён.** '
              'Новый опыт не достиг точечной цели 10% на слабом чистом dev и человеческом dev; шумовой диагностический guardrail провален. '
              'Отдельные благоприятные числа не дают оснований для полного PASS. Поддержка RU/mixed остаётся технической, качество на них не подтверждено.', '',
              'Источники и ограничения: [перечень решений](source-decisions.json), '
              '[реальные HTTP-проверки](source-audit/retrieval.json). '
              'BLeRIOT-A/C и VOICI используются локально с исходными ограничениями лицензий; '
              'новых разрешённых аудиопар из HIWIRE, RU, IEM или DLR получить не удалось. '
              'Результаты всех доступных источников сохранены; ATC не включён в основную задачу.', '',
              'Артефакты: [план](evaluation/plan.json), [все метрики и ответы](evaluation/comparison.json), '
              '[CSV](evaluation/predictions.csv), [CPU smoke](cpu-smoke.json), [верификация](verification.json).', '',
              '![Измерения](measurements.png)', '']
    (root / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    curve = [r for r in history if 'eval_loss' in r]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.1), constrained_layout=True)
    axes[0].plot([r['step'] for r in curve], [r['eval_loss'] for r in curve], marker='o')
    axes[0].set(xlabel='Optimizer step', ylabel='Weak dev loss', title='Expanded-data LoRA: measured loss')
    axes[0].grid(alpha=.25)
    names = ['publisher_weak_dev', 'partial_human_dev', 'general_clean']
    positions = list(range(3))
    for i, (system, title) in enumerate((('parent', 'Parent'), ('expanded', 'Expanded LoRA'))):
        axes[1].bar([x + (i - .5) * .32 for x in positions], [100 * result['cohorts'][c]['scores'][system]['wer_lexical_corpus'] for c in names], width=.32, label=title)
    axes[1].set_xticks(positions, ['Publisher proxy\n35 weak refs', 'Partial human\n5 dev refs', 'General clean\n50 controls'])
    axes[1].set(ylabel='Lexical errors / reference words (%)', title='Different reference cohorts; no release PASS')
    axes[1].legend()
    for ext in ('png', 'svg'):
        fig.savefig(root / f'measurements.{ext}', dpi=160)
    plt.close(fig)
    print(json.dumps({'status': 'RENDERED_MEASURED_ONLY', 'report_sha256': file_hash(root / 'report.md'),
                      'preparation_plan_sha256': file_hash(Path('/expanded/plan.json')), 'source_families': list(plan['source_families'])}))


if __name__ == '__main__':
    main()
