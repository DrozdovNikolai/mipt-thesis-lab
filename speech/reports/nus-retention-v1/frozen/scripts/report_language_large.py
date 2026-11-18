"""Render measured language and model effects without implying release promotion."""

import json
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from north55_speech.core import atomic_json, file_hash, read_yaml  # noqa: E402

ROOT = Path('/reports/language-large-v1')
NAMES = {'publisher_weak_dev': 'Слабые издательские эталоны', 'partial_human_dev': 'Пять пользовательских dev-эталонов',
    'general_clean': 'Общий чистый EN', 'general_ru': 'Общий RU', 'voici_mix_0dB': 'Слабые смеси 0 dB',
    'voici_mix_10dB': 'Слабые смеси 10 dB'}
SYSTEMS = ('small_previous', 'small_known', 'large_known')


def read(path):
    return json.loads(path.read_bytes())


def main():
    result, plan = read(ROOT / 'comparison.json'), read(ROOT / 'plan.json')
    acceptance = read_yaml(Path('/app/ACCEPTANCE.yaml'))['asr_quality_gate']
    diagnostic = {}
    for effect in ('language_effect', 'model_effect'):
        c = result['cohorts']['partial_human_dev']['comparisons'][effect]
        point = c['relative_reduction'] >= acceptance['minimum_relative_wer_reduction']
        ci = c['bootstrap']
        diagnostic[effect] = {'point_target': 'PASS' if point else 'FAIL', 'relative_reduction': c['relative_reduction'],
            'human_dev_bootstrap': ci, 'quality_gate': 'NEEDS_MORE_DATA', 'same_information_and_checkpoint_pipeline_evidence': False}
    diagnostic['model_controls'] = {}
    interpretation = {}
    for cohort, c in result['cohorts'].items():
        interpretation[cohort] = {}
        for effect, comparison in c['comparisons'].items():
            ci = comparison['bootstrap']
            interpretation[cohort][effect] = {
                'finite_interval': ci.get('lower') is not None and ci.get('upper') is not None,
                'independent_sampling_interpretable': ci.get('lower') is not None and ci.get('upper') is not None
                    and ci.get('valid_resamples', 0) > 0 and ci['independent_groups'] > 1,
                'frozen_scorer_flag': comparison['ci_interpretable_for_independent_sampling'],
                'note': 'Frozen scorer flag checks group count alone. Empty-reference noise has no WER interval even with two groups. No measurements or frozen scorer bytes changed.'}
    atomic_json(ROOT / 'ci-interpretation.json', interpretation)
    for cohort in ('general_clean', 'general_ru'):
        delta = result['cohorts'][cohort]['comparisons']['model_effect']['wer_delta']
        diagnostic['model_controls'][cohort] = {'wer_delta': delta, 'point_guardrail': 'PASS' if delta <= acceptance['guardrails']['maximum_clean_wer_absolute_increase'] else 'FAIL'}
    for cohort in ('noise_only', 'bleriot_b_noise'):
        rates = result['cohorts'][cohort]['inserted_words_per_minute']
        delta = rates['large_known'] - rates['small_known']
        diagnostic['model_controls'][cohort] = {'word_rate_delta': delta, 'point_guardrail': 'PASS' if delta <= 0 else 'FAIL', 'reference_status': 'publisher description, no independent listening audit'}
    atomic_json(ROOT / 'diagnostic-gates.json', diagnostic)
    lines = ['# Проверка EN и Whisper large-v3', '',
        '**Обе проверки исполнены. Это development-диагностика; release baseline сохранён. ASR quality gate — NEEDS_MORE_DATA.**', '',
        '## Что сравнивалось', '',
        f"План зафиксирован {plan['frozen_at']}. Сохранены 661 прежний small-ответ; заново выполнены 661 small и 661 large-v3 распознавания. "
        'Всего 1983 записи сравнения, 1322 новых вызова. Все входы сохранены, включая окна без эталона и шум.', '',
        'В пяти пользовательских dev-ревизиях уже был указан EN при подтверждённой области и прослушивании; '
        'старый эксперимент передавал auto. Новый языковой вариант использует именно эти сохранённые отметки. '
        'Остальные 656 входных режимов не менялись: слабым BLeRIOT эталонам английский не назначался по тексту, '
        'русский контроль остаётся RU, неизвестные и шумовые записи остаются auto.', '',
        '1. **Эффект языка:** прежний small/auto → новый small с EN по отметкам. Меняется доступная языковая информация.',
        '2. **Эффект модели:** новый small → large-v3, одинаковая языковая информация и CUDA/float16. Меняется checkpoint.', '',
        'Ни одно из этих сравнений не объявляется доказательством улучшения обработки при неизменных checkpoint и входной информации. '
        'Два новых варианта исчерпали зафиксированный бюджет 16; дообучение и дополнительный поиск не выполнялись.', '',
        'Модель large-v3: [Systran conversion](https://huggingface.co/Systran/faster-whisper-large-v3), '
        'MIT, revision edaa852ec7e145841d8ffdb056a99866b5f0a478. Все 6 файлов проверены по publisher LFS SHA-256 / Git blob SHA-1; '
        'model.bin SHA-256 69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1. '
        'Beam 5, temperature 0, цель transcribe; VAD, denoise, hints и re-decode отключены. Обе GPU модели работали последовательно без сети.', '',
        '## Измеренное качество', '',
        '| Поднабор / эталонов | Прежний small | Small с языком | Large-v3 с тем же языком |', '|---|---:|---:|---:|']
    for cohort, title in NAMES.items():
        if cohort not in result['cohorts']:
            continue
        c = result['cohorts'][cohort]
        values = [f"{100*c['scores'][s]['wer_lexical_corpus']:.2f}%" for s in SYSTEMS]
        lines.append(f"| {title} / {c['references']} | {' | '.join(values)} |")
    lines += ['', '| Эффект на пяти пользовательских фрагментах | Относительное снижение WER | 95% CI ΔWER, процентные пункты |',
        '|---|---:|---:|']
    for effect, title in (('language_effect', 'Язык: small auto → small EN'), ('model_effect', 'Модель: small → large, тот же EN')):
        c = result['cohorts']['partial_human_dev']['comparisons'][effect]
        ci = c['bootstrap']
        lines.append(f"| {title} | {100*c['relative_reduction']:.2f}% | [{100*ci['lower']:.2f}; {100*ci['upper']:.2f}] |")
    lines += ['', 'Пользовательский dev содержит 5 фрагментов, 3 группы и 115 слов; подсказки показывались при разметке, '
        'запись чисел и отдельные языковые места остаются ограничением эталона. Текст и нормализатор не исправлялись под результат. '
        'Издательские пары имеют слабую автоматическую привязку; RU не имеет speaker IDs и образует один консервативный кластер.', '',
        '| Шум по описанию издателя | Small, слов/мин | Large-v3, слов/мин |', '|---|---:|---:|']
    for cohort in ('noise_only', 'bleriot_b_noise'):
        c = result['cohorts'][cohort]
        lines.append(f"| {cohort} | {c['inserted_words_per_minute']['small_known']:.4f} | {c['inserted_words_per_minute']['large_known']:.4f} |")
    lines += ['', 'Шум оценивается по пустому эталону издателя, без независимой проверки отсутствия речи. '
        'BLeRIOT-B измерен в канало-минутах, а не независимых полётах.', '',
        'Paired cluster bootstrap: 2000 повторов, seed 55, 95% CI для candidate − baseline. '
        'Числа, размеры групп и интервалы приведены в [comparison.json](comparison.json) и [diagnostic-gates.json](diagnostic-gates.json). '
        'Одногрупповые интервалы на RU и смесях не интерпретируются как статистическое подтверждение. '
        'Для пустых шумовых эталонов WER-интервала нет даже при двух группах; '
        '[ci-interpretation.json](ci-interpretation.json) уточняет групповой флаг замороженного scorer без изменения метрик.', '',
        '## Время и память', '', '| Свежий GPU запуск | ASR, с | ASR RTF | Driver RTF |', '|---|---:|---:|---:|']
    for s, t in result['timing'].items():
        lines.append(f"| {s} | {t['asr_seconds']:.2f} | {t['asr_rtf']:.4f} | {t['driver_rtf']:.4f} |")
    timings = {}
    lines += ['', '| Поднабор | Small ASR RTF | Large ASR RTF |', '|---|---:|---:|']
    for cohort in result['cohorts']:
        timings[cohort] = {}
        for system in plan['systems']:
            rows = [r for r in result['rows'] if r['system'] == system and r['cohort'] == cohort]
            duration = sum(r['duration_sec'] for r in rows)
            elapsed = sum(r['asr_elapsed_sec'] for r in rows)
            timings[cohort][system] = {'audio_seconds': duration, 'asr_seconds': elapsed, 'asr_rtf': elapsed / duration}
        lines.append(f"| {NAMES.get(cohort, cohort)} | {timings[cohort]['small_known']['asr_rtf']:.4f} | {timings[cohort]['large_known']['asr_rtf']:.4f} |")
    atomic_json(ROOT / 'runtime-by-cohort.json', timings)
    lines += ['', 'RTF = время обработки / длительность аудио. ASR RTF исключает инициализацию, очередь и UI; '
        'driver дополнительно учитывает чтение/проверку аудио. Это не end-to-end время приложения.', '',
        '| Запуск | Инициализация, с | GPU до модели, MiB | Наблюдённый максимум GPU, MiB | Максимум RSS процесса, MiB |', '|---|---:|---:|---:|---:|']
    for s in plan['systems']:
        for p in sorted((ROOT / s).glob('runtime-*.json')):
            r = read(p)
            m = r['memory']
            lines.append(f"| {s} ({r['status']}) | {r.get('initialization_sec', 0):.2f} | {m['device_before_model_mib']} | {m['sampled_device_peak_mib']} | {m['process_peak_rss_kib']/1024:.1f} |")
    lines += ['', 'GPU память опрашивалась с целевым шагом 0,5 с через nvidia-smi. Это память всего устройства, '
        'включая другие приложения; краткие пики между опросами могут быть пропущены. RSS относится к CPU памяти процесса.', '',
        f"Совпадение новых small-ответов с прежними на неизменных языковых режимах: {result['unchanged_language_exact_replays']}/{result['unchanged_language_inputs']}. "
        f"Ошибки вызовов ASR: {result['runtime_failures']}.", '',
        '## Статус и воспроизведение', '',
        'Независимый кабинный final test и критические сущности по-прежнему отсутствуют в необходимом объёме. '
        'Candidate не выбран, serving baseline и пользовательские ревизии сохранены; результаты не заменяют NLP/temporal gates.', '',
        '[Тексты пяти фрагментов](human-fragments.md) · [Протокол](protocol.md) · [замороженный план](plan.json) · [CPU smoke](cpu-smoke.json) · '
        '[проверки артефактов](verification.json) · [PowerShell/Linux replay](score-reproduction.json).', '',
        '![WER](measurements.png)', '']
    (ROOT / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    examples = ['# Тексты на пяти пользовательских dev-фрагментах', '',
        'Сохранённые эталоны и все три машинных ответа. Разметка не исправлялась под модели; '
        'спорные числа и языковые места остаются ограничением этой диагностики.', '']
    lookup = {(r['system'], r['id']): r for r in result['rows']}
    review_path = Path('/reviewed/dev.jsonl')
    if file_hash(review_path) != plan['reviewed_manifest_sha256']:
        raise ValueError('Display metadata no longer matches frozen reviews')
    reviews = {'reviewed-' + r['sample_id']: r for r in [json.loads(line) for line in review_path.read_text().splitlines()]}
    for item in read(ROOT / 'inputs.json'):
        if item['cohort'] != 'partial_human_dev':
            continue
        review = reviews[item['id']]
        provenance = review['annotation_provenance']
        title = review['recording_id'].strip() + f" · {provenance['original_start_sec']}–{provenance['original_end_sec']} с оригинала"
        examples += ['## ' + title, '', '`' + item['id'] + '`', '',
            '**Сохранённый эталон:** ' + lookup['small_previous', item['id']]['reference'], '']
        for system, label in zip(SYSTEMS, ('Small, прежний auto', 'Small, EN по отметкам', 'Large-v3, EN по тем же отметкам'), strict=True):
            row = lookup[system, item['id']]
            errors = sum(row['score'][k] for k in ('S', 'D', 'I'))
            examples += [f'**{label}:** ' + row['hypothesis'], '', f"Ошибок: {errors} / {row['score']['N']} слов.", '']
    (ROOT / 'human-fragments.md').write_text('\n'.join(examples), encoding='utf-8')
    selected = ('partial_human_dev', 'publisher_weak_dev', 'general_clean', 'general_ru')
    fig, ax = plt.subplots(figsize=(9.5, 4.8), constrained_layout=True)
    x = np.arange(len(selected))
    for n, (system, label) in enumerate(zip(SYSTEMS, ('Small previous', 'Small known language', 'Large-v3 same language'), strict=True)):
        ax.bar(x + (n - 1) * .25, [100 * result['cohorts'][c]['scores'][system]['wer_lexical_corpus'] for c in selected], width=.25, label=label)
    ax.set_xticks(x, ['Partial human\n5 refs / 3 groups', 'Weak publisher\n35 refs', 'General clean EN\n50 refs', 'General RU\n50 refs / 1 group'])
    ax.set(ylabel='Lexical WER (%)', title='Language and checkpoint diagnostics; no release PASS')
    ax.legend(fontsize=9)
    for ext in ('png', 'svg'):
        fig.savefig(ROOT / f'measurements.{ext}', dpi=160)
    plt.close(fig)
    print(json.dumps({'status': 'RENDERED_MEASURED', 'report_sha256': file_hash(ROOT / 'report.md')}))


if __name__ == '__main__':
    main()
