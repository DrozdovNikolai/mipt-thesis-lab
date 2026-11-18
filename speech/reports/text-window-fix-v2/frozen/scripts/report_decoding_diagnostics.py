"""Verify frozen diagnostics and render deterministic reports using the stdlib."""

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/decoding-v1'
SYSTEMS = tuple(f'{m}_{v}' for m in ('parent', 'augmented') for v in ('baseline', 'text', 'vad'))


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def main():
    plan, result = read(ROOT / 'plan.json'), read(ROOT / 'comparison.json')
    items = read(ROOT / 'inputs.json')
    previous = read(REPO / 'reports/retraining-v1/evaluation/plan.json')
    checks = {
        'frozen_source_files': all(sha(ROOT / 'frozen' / n) == h for n, h in read(ROOT / 'frozen-files.json').items()),
        'unchanged_acceptance': sha(REPO / 'ACCEPTANCE.yaml') == plan['acceptance_sha256'] == '32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071',
        'unchanged_baseline': sha(REPO / 'configs/baseline.yaml') == plan['baseline_sha256'] == '419accafb0874a51c11bd4865117a4daf761345a48242e36269c71e88a73e1d1',
        'unchanged_SPEC': sha(REPO / 'SPEC.md') == '9191d785add8109b4a3edd75171fab81987aac5df34036cb34daecbbe4de644f',
        'unchanged_SOURCES': sha(REPO / 'SOURCES.md') == '74e70ac86c48d423f9a3da3d3d6bd8a13ee32cab6e537502ba0f12c3a939f114',
        'unchanged_retraining_plan': sha(REPO / 'reports/retraining-v1/evaluation/plan.json') == plan['previous_plan_sha256'] == '164153f9c0fb72df977fa71e56ce892381e6c67b21b2140701da8e1a0e21870b',
        'same_scorer': plan['scorer_sha256'] == previous['scorer_sha256'],
        'unchanged_references': sha(REPO / 'data/curated/language-large-v1/scoring/references.json') == plan['references_sha256'] == previous['references_sha256'],
        'same_checkpoints': all(plan['models'][m] == previous['models'][m] for m in ('parent', 'augmented')),
        'frozen_inputs': sha(ROOT / 'inputs.json') == plan['inputs_sha256'] and len(items) == 264,
        'frozen_protocol': sha(ROOT / 'protocol.md') == plan['protocol_sha256'],
        'result_plan': result['plan_sha256'] == sha(ROOT / 'plan.json'),
        'all_results_and_counts': result['records'] == 1584 and result['new_predictions'] == 1084 and len(read(ROOT / 'scored-counts.json')) == 1584,
        'no_release_or_final_test_claim': result['release_promoted'] is False and result['test_accessed'] is False,
        'exact_additional_budget': plan['new_configuration_budget'] == 4 and plan['cumulative_configurations'] == 22,
    }
    by_id = {i['id']: i for i in items}
    checks['quiet_groups_and_reference_links'] = all(
        i['gain_db'] == -12 and i['group_id'] == by_id[i['reference_id']]['group_id']
        and i['audio_sha256'] == by_id[i['reference_id']]['audio_sha256']
        for i in items if i['gain_db'])
    checks['noise_at_least_five_minutes_each'] = all(sum(i['duration_sec'] for i in items if i['cohort'] == c) >= 300
                                                        for c in ('noise_only', 'bleriot_b_noise'))
    lookup, resumed, cpu = {}, {}, {}
    for model in ('parent', 'augmented'):
        path = ROOT / 'controls' / (model + '.json')
        controls = read(path)
        checks[model + '_control_hashes'] = sha(path) == plan['controls_sha256'][model] and len(controls) == 250
        lookup.update({(model + '_baseline', k): v for k, v in controls.items()})
    for system in SYSTEMS:
        output = ROOT / system
        execution = read(output / 'execution.json')
        records = [read(output / 'predictions' / n) for n in execution['prediction_sha256']]
        expected = 14 if system.endswith('_baseline') else 264
        checks[system + '_complete_hashes'] = len(records) == expected and all(
            sha(output / 'predictions' / n) == h for n, h in execution['prediction_sha256'].items())
        checks[system + '_runtime_hashes'] = all(sha(output / n) == h for n, h in execution['runtime_sha256'].items())
        checks[system + '_plan_and_options'] = all(r['plan_sha256'] == sha(ROOT / 'plan.json')
            and r['config'] == plan['configs'][system]
            and r['effective_options']['without_timestamps'] == system.endswith('_text')
            and r['effective_options']['word_timestamps'] is True for r in records)
        checks[system + '_no_runtime_failure'] = all(r['runtime_failure'] is None for r in records)
        runtimes = [read(output / n) for n in execution['runtime_sha256']]
        checks[system + '_actual_cuda_float16'] = all(r['actual_device'] == 'cuda' and r['actual_precision'] == 'float16' for r in runtimes)
        checks[system + '_freeze_before_inference'] = all(plan['frozen_at'] < r['started_at'] for r in runtimes)
        resumed[system] = [r['resumed_records'] for r in runtimes if r['new_records'] == 0]
        lookup.update({(system, r['id']): r for r in records})
    for system in (s for s in SYSTEMS if not s.endswith('_baseline')):
        model = system.split('_')[0]
        baseline = model + '_baseline'
        checks[system + '_only_declared_options_changed'] = all(
            {k: v for k, v in lookup[system, i['id']]['effective_options'].items() if k != 'without_timestamps'} ==
            {k: v for k, v in lookup[baseline, i['id']]['effective_options'].items() if k != 'without_timestamps'} for i in items)
        output = ROOT / ('cpu-' + system)
        execution = read(output / 'execution.json')
        records = [read(output / 'predictions' / n) for n in execution['prediction_sha256']]
        runtimes = [read(output / n) for n in execution['runtime_sha256']]
        checks[system + '_CPU_hashes'] = len(records) == 4 and all(sha(output / 'predictions' / n) == h for n, h in execution['prediction_sha256'].items())
        checks[system + '_CPU_execution'] = all(r['runtime_failure'] is None for r in records) and all(r['actual_device'] == 'cpu' for r in runtimes)
        cpu[system] = {'records': len(records), 'actual_precisions': sorted({r['actual_precision'] for r in runtimes}),
                       'runtime_failures': sum(r['runtime_failure'] is not None for r in records),
                       'quality_status': 'NOT_EVALUATED_CPU_SMOKE'}
    checks['resume_parent_vad'] = 264 in resumed['parent_vad']
    snapshots = [read(p) for p in sorted(ROOT.glob('north55-decoding-v1-*.json'))]
    inference = [s for s in snapshots if any(x in s['command'] for x in ('infer', 'cpu'))]
    checks['all_inference_offline_exit_zero'] = bool(inference) and all(s['network_mode'] == 'none' and s['state']['ExitCode'] == 0 for s in inference)
    allowed = {'/app/scripts', '/app/src', '/app/configs', '/app/SPEC.md', '/app/SOURCES.md',
               '/app/ACCEPTANCE.yaml', '/app/uv.lock', '/audio', '/models',
               '/study/plan.json', '/study/inputs.json', '/study/protocol.md'}
    checks['inference_mounts_exclude_refs_controls_train'] = all(
        {m['Destination'] for m in s['mounts']} <= allowed | {'/study/' + ('cpu-' if 'cpu' in s['command'] else '') + s['command'][-1]}
        for s in inference)
    checks['only_own_prediction_output_writable'] = all(sum(m['RW'] for m in s['mounts']) == 1 for s in inference)
    suites = [ET.parse(p).getroot() for p in ROOT.glob('tests-*.xml')]
    checks['contract_tests_pass'] = any(int(s.get('tests', 0)) == 9 and not int(s.get('failures', 0)) and not int(s.get('errors', 0))
                                       for root in suites for s in root.iter('testsuite'))
    release = read(ROOT / 'serving-status.json')
    checks['serving_baseline_unchanged'] = (release['model'], release['device'], release['compute_type'], release['deployment_candidate'], release['validated_scope']) == ('small', 'cpu', 'int8', 'baseline', [])
    verification = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
                    'failed': [k for k, v in checks.items() if not v], 'cpu_smoke': cpu,
                    'resume_counts': resumed, 'scope': 'Artifact/execution verification, not ML quality PASS.'}
    save(ROOT / 'verification.json', verification)
    save(ROOT / 'status.json', {'implemented': ['isolated text decoding and VAD', 'original timeline alignment', 'bounded frozen protocol', 'quiet and short retention diagnostics', 'offline resumable launcher and reports'],
        'executed': {'GPU_new_predictions': 1084, 'GPU_reused_controls': 500, 'CPU_smoke_predictions': 16, 'new_training_runs': 0},
        'verified': verification['status'], 'diagnostic_gates': result['gates'],
        'asr_quality_gate': result['asr_quality_gate'], 'critical_entity_gate': 'NEEDS_MORE_DATA',
        'nlp_quality_gate': 'NEEDS_MORE_DATA', 'temporal_detection_gate': 'NEEDS_MORE_DATA',
        'full_word_timestamp_coverage': {s: 'PASS' if a['nonempty_segments_without_words'] == 0 else 'FAIL'
                                         for s, a in result['alignment'].items()},
        'release_promoted': False, 'test_accessed': False})
    lines = ['# Декодирование и VAD: реальные результаты', '',
        'Четыре заранее фиксированных варианта проверены на сохранённых parent и augmented433 весах. '
        'Нового обучения не было. Эталоны, lexical scorer, ACCEPTANCE и рабочий baseline сохранены.', '',
        '## Lexical WER (%)', '',
        '| Набор | Число | Parent | Parent text | Parent VAD | Augmented | Augmented text | Augmented VAD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in ('partial_human_dev', 'publisher_weak_dev', 'general_clean', 'general_ru', 'voici_mix_0dB', 'voici_mix_10dB',
                 'short_general_clean', 'quiet_general_clean', 'quiet_partial_human_dev'):
        cohort = result['cohorts'][name]
        lines.append(f'| {name} | {cohort["inputs"]} | ' + ' | '.join(f'{100*cohort["systems"][s]["counts"]["wer_lexical_corpus"]:.2f}' for s in SYSTEMS) + ' |')
    lines += ['', '## Проверка двух гипотез', '']
    for system in (s for s in SYSTEMS if not s.endswith('_baseline')):
        c = result['cohorts']['partial_human_dev']['comparisons'][system]
        a, b, ci = c['baseline'], c['candidate'], c['bootstrap']
        lines.append(f'- **{system}**: на пяти кабинных dev-фрагментах относительное снижение WER '
            f'{100*c["relative_reduction"]:.2f}%; 95% CI ΔWER [{100*ci["lower"]:.2f}; {100*ci["upper"]:.2f}] п.п. '
            f'S/D/I: {a["S"]}/{a["D"]}/{a["I"]} → {b["S"]}/{b["D"]}/{b["I"]}. '
            f'Порог 10%: {result["gates"][system]["human_dev_point_target"]}; release: {result["gates"][system]["release"]}.')
    lines += ['', 'Отрицательное «снижение» означает ухудшение. Каждое сравнение использует собственный checkpoint baseline. '
        'Пять фрагментов/115 слов/три группы уже участвовали в прошлых диагностиках: статистическое подтверждение '
        'обобщения **INCONCLUSIVE**; основной quality gate **NEEDS_MORE_DATA**.', '',
        '## Ложные вставки на шуме (слов/мин)', '',
        '| Набор | Минут | Parent | Parent text | Parent VAD | Augmented | Augmented text | Augmented VAD |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in ('noise_only', 'bleriot_b_noise'):
        c = result['cohorts'][name]
        lines.append(f'| {name} | {c["channel_minutes"]:.2f} | ' + ' | '.join(f'{c["systems"][s]["inserted_words_per_minute"]:.3f}' for s in SYSTEMS) + ' |')
    lines += ['', '## Пропуски тихих/коротких реплик', '',
        'В ячейке: D (удалённые слова) / пустые ответы. Короткие реплики общей EN речи — '
        'контроль чувствительности, а не проверенная разметка кабинных команд.', '',
        '| Набор | Parent | Parent text | Parent VAD | Augmented | Augmented text | Augmented VAD |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name in ('short_general_clean', 'quiet_general_clean', 'quiet_partial_human_dev'):
        c = result['cohorts'][name]
        lines.append(f'| {name} | ' + ' | '.join(f'{c["systems"][s]["counts"]["D"]} / {c["systems"][s]["empty_hypotheses"]}' for s in SYSTEMS) + ' |')
    lines += ['', '## Полнота выравнивания', '',
        '| Система | Выровненные слова | Сегменты с текстом без словесных границ | Слова нулевой длительности |',
        '|---|---:|---:|---:|']
    for system, a in result['alignment'].items():
        lines.append(f'| {system} | {a["words"]} | {a["nonempty_segments_without_words"]} | {a["zero_duration_words"]} |')
    lines += ['', 'Отсутствующие границы не заменены вымышленными. В text-режиме встретились '
        'повторяющиеся последовательности символов на шуме/сильной смеси, для которых backend не вернул '
        'word alignment. Они сохранены и входят в lexical scoring; длинная последовательность без пробелов '
        'может считаться одним вставленным словом, поэтому слов/мин недостаточно для описания такого сбоя.', '',
        '## Исполнение и ограничения', '',
        f'- 1084 новых GPU-прогноза, 500 проверенных прежних baseline-ответов; ошибки: {sum(result["runtime_failures"].values())}.',
        '- CUDA float16 у всех GPU-вариантов; 16 отдельных CPU smoke. CPU качество не смешивается с GPU-метриками.',
        f'- Проверка артефактов: **{verification["status"]}**, {len(checks)} проверок. Технический PASS не означает ML PASS.',
        '- Проверены хеши источников, весовых манифестов, эталонов, предсказаний и отсутствие доступа inference к эталонам/controls/train.',
        '- Выравнивание проверяет диапазон координат, не точность относительно человеческой временной разметки. '
        'Нулевые длительности и отсутствие выровненных слов сохранены в comparison.json.',
        '- Quiet-копии сохраняют оригинальную группу. Их нельзя считать независимыми дополнительными эталонами.',
        '- Критические сущности и временные границы коротких команд недостаточны: **NEEDS_MORE_DATA**. '
        'NLP/temporal detection не переобучались и не получили новых человеческих labels.',
        '- RU измерен на общей речи; кабинный RU и mixed остаются неподтверждёнными.',
        '- Повторы не удалялись. Несоответствие повторов эталону само по себе не доказывает галлюцинацию.',
        '- В рабочем сервисе остаётся small / CPU int8 / baseline. Ни один диагностический вариант не продвинут.',
        '', 'Команды, структура файлов и ограничения: `docs/decoding_diagnostics.md`.', '']
    (ROOT / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'verification': verification['status'], 'checks': len(checks), 'failed': verification['failed']}, ensure_ascii=False))
    if verification['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except PermissionError:
        if '--in-container' in sys.argv:
            raise
        args = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python']
        sources = [(ROOT, '/app/reports/decoding-v1', False),
                   (Path(__file__).resolve(), '/app/scripts/report_decoding_diagnostics.py', True),
                   *[(REPO / n, '/app/' + n, True) for n in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml',
                      'reports/retraining-v1/evaluation/plan.json', 'data/curated/language-large-v1/scoring/references.json')]]
        for local, remote, readonly in sources:
            args += ['-v', f'{local.as_posix()}:{remote}' + (':ro' if readonly else '')]
        args += ['north55-speech-gpu:0.1.0', '/app/scripts/report_decoding_diagnostics.py', '--in-container']
        raise SystemExit(subprocess.run(args, check=False).returncode) from None
