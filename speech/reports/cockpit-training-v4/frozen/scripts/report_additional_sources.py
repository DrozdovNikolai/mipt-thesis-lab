"""Render only measured additional-source ASR and native NLP results."""

import json
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from north55_speech.core import atomic_json, file_hash, read_yaml

ROOT = Path('/reports/additional-sources-v1')
NAMES = {'baseline': 'Baseline', 'vad_segments': 'VAD segments', 'vad_gate': 'VAD gate', 'vad_span': 'VAD span', 'vad_gate_denoise': 'VAD gate + denoise'}
COHORTS = {'publisher_weak_dev': 'BLeRIOT: слабые чистые эталоны', 'partial_human_dev': 'Пять пользовательских dev-расшифровок',
    'general_clean': 'LibriSpeech EN: общий чистый контроль', 'general_ru': 'FLEURS RU: общий контроль',
    'voici_mix_0dB': 'Слабые смеси VOICI 0 dB', 'voici_mix_10dB': 'Слабые смеси VOICI 10 dB'}


def read(path):
    return json.loads(path.read_bytes())


def main():
    result = read(ROOT / 'asr/comparison.json')
    plan = read(ROOT / 'asr/plan.json')
    cvr = read(ROOT / 'cvr-preparation.json')
    native = read(ROOT / 'nlp-final/comparison.json')
    native_selection = read(ROOT / 'nlp-final/final-selection.json')
    acceptance = read_yaml(Path('/app/ACCEPTANCE.yaml'))['asr_quality_gate']
    guards = acceptance['guardrails']
    diagnostics = {}
    for trial in plan['trials'][1:]:
        weak = result['cohorts']['publisher_weak_dev']['comparisons'][trial]
        human = result['cohorts']['partial_human_dev']['comparisons'][trial]
        clean = result['cohorts']['general_clean']['comparisons'][trial]['wer_delta']
        noise = {c: result['cohorts'][c]['inserted_words_per_minute'][trial] - result['cohorts'][c]['inserted_words_per_minute']['baseline'] for c in ('noise_only', 'bleriot_b_noise')}
        diagnostics[trial] = {'clean': 'PASS' if clean <= guards['maximum_clean_wer_absolute_increase'] else 'FAIL',
            'noise_publisher_assumptions': {c: 'PASS' if delta <= guards['maximum_non_speech_inserted_words_per_minute_delta'] else 'FAIL' for c, delta in noise.items()},
            'weak_point_target': 'PASS' if weak['relative_reduction'] >= acceptance['minimum_relative_wer_reduction'] else 'FAIL',
            'human_point_target': 'PASS' if human['relative_reduction'] >= acceptance['minimum_relative_wer_reduction'] else 'FAIL',
            'human_CI_upper': human['bootstrap']['upper'], 'formal_quality_gate': 'NEEDS_MORE_DATA'}
    atomic_json(ROOT / 'diagnostic-gates.json', diagnostics)
    lines = ['# Дополнительные источники и проверка обработки пауз', '',
        '**Новые данные действительно получены и использованы. Рабочий baseline сохранён; общий ASR/NLP quality gate — NEEDS_MORE_DATA.**', '',
        '- BLeRIOT-B: все 7 файлов, 5 архивов, 102 проверенных WAV/NPY; шумовая часть дала 87 отдельных каналов. '
        'Микрофоны и каналы коррелированы, группировка консервативно по двум самолётам. Импульсные отклики проверены как данные, но не выданы за новые независимые голоса.',
        '- Google FLEURS: официальный RU dev, tar/TSV проверены по pinned checksums; 50 фраз выбраны по seed/hash до ASR. '
        'Это общая русская речь. Идентификаторов говорящих нет: один консервативный кластер, без заявления о кабинном RU качестве.',
        f"- Noort CVR: получены {cvr['raw_rows']} строки с человеческими исходными метками; строгий отбор CVR/CAM/HOT/INT/экипажа оставил "
        f"{sum(s['rows'] for s in cvr['splits'].values())} реплику. Train/dev/holdout: 2838/394/49 реплик, 24/7/1 случая. Это отдельная текстовая задача safety voice.", '',
        'Лицензии, HTTP-проверки и причины отказа остальных источников: [source-decisions.json](source-decisions.json). '
        'У DLR и EARS нашлись публикации, но не разрешённые выгрузки raw audio/data. Pilot Speech Corpus оказался корпусом банковской биометрии; ICSRC — автомобильной речью.', '',
        '## ASR: одинаковые модель и precision', '',
        f"**{result['output_records']} результатов сравнения на 661 входе**: {result['reused_baseline_records']} прежних baseline-ответа переиспользованы с проверкой SHA-256, "
        f"остальные {result['output_records'] - result['reused_baseline_records']} результаты получены новым исполнением стадий. "
        f"Фактических новых вызовов ASR: {result['new_asr_calls']}; пустых выходов без вызова модели после VAD: {result['gated_empty_outputs']}; "
        f"сбоев исполнения ASR: {result['runtime_failures']}.", '',
        'Тот же pinned whisper-small parent, фактический CUDA/float16, beam 5, temperature 0, одинаковая информация о языке. '
        'Нет эталонных prompts, hints или повторного ASR. VAD segments — прежнее разбиение; gate пропускает исходник целиком при наличии речи; '
        'span сохраняет промежуточные паузы и обрезает только внешние, с дополнительным запасом 400 мс; последний вариант добавляет существующий denoise strength 0,3. '
        'План всех вариантов заморожен до inference, исходники сохранены отдельно.', '',
        '| Поднабор (число эталонов) | Baseline WER | Segments | Gate | Span | Gate + denoise |',
        '|---|---:|---:|---:|---:|---:|']
    for cohort, title in COHORTS.items():
        value = result['cohorts'][cohort]
        scores = [f"{value['scores'][t]['wer_lexical_corpus']:.2%}" for t in plan['trials']]
        lines.append(f"| {title} ({value['scored']}) | " + ' | '.join(scores) + ' |')
    lines += ['', 'Сценарии после автоматической привязки остаются слабыми эталонами. Все объявленные окна сохранены; '
        'для окна без эталона WER не выдуман. Пользовательский dev содержит только три группы и прежнее воздействие подсказок.', '',
        '| Шум по заявлению издателя | Baseline слов/мин | Segments | Gate | Span | Gate + denoise |',
        '|---|---:|---:|---:|---:|---:|']
    for cohort, title in (('noise_only', 'VOICI'), ('bleriot_b_noise', 'BLeRIOT-B')):
        c = result['cohorts'][cohort]
        lines.append('| ' + title + ' | ' + ' | '.join(f"{c['inserted_words_per_minute'][t]:.4f}" for t in plan['trials']) + ' |')
    lines += ['', 'Для BLeRIOT-B знаменатель — сумма длительностей каналов, а не время независимых полётов. '
        'Пустой эталон шума опирается на описание издателя; независимой человеческой проверки отсутствия речи нет.', '',
        '| Вариант | Чистый EN контроль | VOICI / B noise | Цель 10%: слабый dev / человеческий dev | 95% CI ΔWER: человеческий dev |',
        '|---|---|---|---|---|']
    for trial, diagnostic in diagnostics.items():
        interval = result['cohorts']['partial_human_dev']['comparisons'][trial]['bootstrap']
        lines.append(f"| {NAMES[trial]} | {diagnostic['clean']} | " + ' / '.join(diagnostic['noise_publisher_assumptions'].values()) +
            f" | {diagnostic['weak_point_target']} / {diagnostic['human_point_target']} | [{interval['lower']:.6f}; {interval['upper']:.6f}] |")
    lines += ['', 'CI: paired cluster bootstrap, 2000 повторов, seed 55, delta = вариант − baseline. '
        'Для одного RU кластера и одного источника шума в смесях bootstrap вырожден; статистическая значимость на них не заявлена. '
        'Благоприятный диагностический результат не заменяет недостающие независимые кабинные эталоны и критические сущности. '
        '**Ни один этап не активирован в release.**', '',
        '## NLP: реальные человеческие исходные метки', '',
        'Обучены TF-IDF word/char + logistic regression: 9 вариантов C/threshold и ещё 3 с предыдущей репликой. '
        'Контекст включает только предыдущую принятую реплику при последовательных номерах строк; не включает будущее, метки, роль, исход аварии или текст исключённого радиообмена. '
        'Сравнение сохранено с прежними project hazard rules и отдельными более широкими фиксированными hazard rules. '
        'Выбор выполнен по dev macro-F1, затем зафиксирован перед holdout inference. Размеченные ответы недоступны контейнеру inference.', '',
        '| Dev, 394 реплики / 7 случаев | Precision safety voice | Recall | F1 safety voice | Macro-F1 |',
        '|---|---:|---:|---:|---:|']
    for name, score in native_selection['source_dev_scores'].items():
        voice = score['safety_voice']
        lines.append(f"| {name} | {voice['precision']:.4f} | {voice['recall']:.4f} | {voice['f1']:.4f} | {score['macro_f1']:.4f} |")
    lines += ['', '| Holdout, 49 реплик / 1 случай | Precision safety voice | Recall | F1 safety voice | Macro-F1 |',
        '|---|---:|---:|---:|---:|']
    for name, score in native['scores'].items():
        voice = score['safety_voice']
        lines.append(f"| {name} | {voice['precision']:.4f} | {voice['recall']:.4f} | {voice['f1']:.4f} | {score['macro_f1']:.4f} |")
    lines += ['', '**NLP результат — INCONCLUSIVE:** один принятый holdout-случай недостаточен для обобщения; '
        'на нём обученный вариант уступил широким правилам. После этого результата модель не перенастраивалась. '
        'Человеческие coding_safety_voice не переименованы в CHECKLIST, CREW_COORDINATION или проектную значимость. '
        'Это классификация текстовой реплики, не temporal event detection; оценки модели не калиброваны.', '',
        '## Проверка исполнения и воспроизведение', '',
        '15 контрактных тестов; реальное новое RU/noise CPU исполнение с фактическим int8_float32; '
        'все контейнеры inference/training работают без сети. Исторические полные CPU E2E и проверки восстановления не переименованы в новые прогоны.', '',
        '[Проверка артефактов](verification.json), [полные ASR метрики](asr/comparison.json), '
        '[NLP holdout](nlp-final/comparison.json), [замороженный ASR план](asr/plan.json), '
        '[CPU smoke](cpu-smoke.json), [PowerShell/Linux пересчёт](score-reproduction.json).', '',
        '![Измерения](measurements.png)', '']
    (ROOT / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    columns = ('publisher_weak_dev', 'partial_human_dev', 'general_ru')
    x = np.arange(3)
    for n, trial in enumerate(plan['trials']):
        axes[0].bar(x + (n - 2) * .15, [100 * result['cohorts'][c]['scores'][trial]['wer_lexical_corpus'] for c in columns], width=.15, label=NAMES[trial])
    axes[0].set_xticks(x, ['Weak publisher\n35 refs', 'Partial human\n5 refs', 'General RU\n50 refs'])
    axes[0].set(ylabel='Lexical WER (%)', title='Measured diagnostic cohorts; no release PASS')
    for n, trial in enumerate(plan['trials']):
        axes[1].bar(np.arange(2) + (n - 2) * .15, [result['cohorts'][c]['inserted_words_per_minute'][trial] for c in ('noise_only', 'bleriot_b_noise')], width=.15, label=NAMES[trial])
    axes[1].set_xticks([0, 1], ['VOICI\n1 original', 'BLeRIOT-B\n2 aircraft groups'])
    axes[1].set(ylabel='Inserted words / channel minute', title='Noise under publisher speech-absence assumption')
    axes[1].legend(fontsize=8)
    for ext in ('png', 'svg'):
        fig.savefig(ROOT / f'measurements.{ext}', dpi=160)
    plt.close(fig)
    print(json.dumps({'status': 'RENDERED_MEASURED_ONLY', 'report_sha256': file_hash(ROOT / 'report.md')}))


if __name__ == '__main__':
    main()
