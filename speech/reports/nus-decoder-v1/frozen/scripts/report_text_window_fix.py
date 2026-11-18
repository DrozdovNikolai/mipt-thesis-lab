"""Verify repair artifacts and report failed safeguards without changing them."""

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/text-window-fix-v4'
SYSTEMS = ('parent_reference', 'parent_text', 'augmented_reference', 'augmented_text')


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def main():
    plan, result = read(ROOT / 'plan.json'), read(ROOT / 'comparison.json')
    regression = read(ROOT / 'regressions/result.json')
    items = read(ROOT / 'inputs.json')
    old = REPO / 'reports/decoding-v1'
    checks = {
        'frozen_files': all(sha(ROOT / 'frozen' / n) == h for n, h in read(ROOT / 'frozen-files.json').items()),
        'frozen_inputs': sha(ROOT / 'inputs.json') == plan['inputs_sha256'] == sha(old / 'inputs.json'),
        'frozen_protocol': sha(ROOT / 'protocol.md') == plan['protocol_sha256'],
        'model_manifests_unchanged': plan['models'] == read(old / 'plan.json')['models'],
        'same_scorer': plan['scorer_sha256'] == read(old / 'plan.json')['scorer_sha256'],
        'same_references': plan['references_sha256'] == sha(REPO / 'data/curated/language-large-v1/scoring/references.json'),
        'acceptance_unchanged': sha(REPO / 'ACCEPTANCE.yaml') == plan['acceptance_sha256'] == '32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071',
        'baseline_config_unchanged': sha(REPO / 'configs/baseline.yaml') == '419accafb0874a51c11bd4865117a4daf761345a48242e36269c71e88a73e1d1',
        'SPEC_unchanged': sha(REPO / 'SPEC.md') == '9191d785add8109b4a3edd75171fab81987aac5df34036cb34daecbbe4de644f',
        'SOURCES_unchanged': sha(REPO / 'SOURCES.md') == '74e70ac86c48d423f9a3da3d3d6bd8a13ee32cab6e537502ba0f12c3a939f114',
        'old_measurements_unchanged': all(sha(old / n) == h for n, h in read(old / 'powershell-report-hashes.json').items()),
        'complete_population': len(items) == 264 and result['new_predictions'] == 1056 and len(read(ROOT / 'scored-counts.json')) == 2112,
        'result_plan_link': result['plan_sha256'] == sha(ROOT / 'plan.json'),
        'regression_plan_link': regression['plan_sha256'] == sha(ROOT / 'plan.json'),
        'tail_loop_mechanically_fixed': regression['checks']['original_decoded_once'] and regression['checks']['repeated_decodes_two_spoken_copies'],
        'failed_repeat_check_retained': regression['status'] == 'FAIL' and regression['checks']['both_utterances_retained'] is False,
        'actual_regression_word_times': regression['checks']['nonempty_original_alignment'] and regression['checks']['translated_word_times_in_range'],
        'license_preserved': (ROOT / 'frozen/src/north55_speech/vendor/faster_whisper_LICENSE.txt').is_file(),
    }
    replay = {}
    for system in SYSTEMS:
        output = ROOT / system
        execution = read(output / 'execution.json')
        records = [read(output / 'predictions' / n) for n in execution['prediction_sha256']]
        checks[system + '_prediction_hashes'] = len(records) == 264 and all(sha(output / 'predictions' / n) == h for n, h in execution['prediction_sha256'].items())
        checks[system + '_runtime_hashes'] = all(sha(output / n) == h for n, h in execution['runtime_sha256'].items())
        runtimes = [read(output / n) for n in execution['runtime_sha256']]
        checks[system + '_cuda_float16'] = all(r['actual_device'] == 'cuda' and r['actual_precision'] == 'float16' for r in runtimes)
        checks[system + '_zero_runtime_failures'] = all(r['runtime_failure'] is None for r in records)
        checks[system + '_frozen_before_inference'] = all(plan['frozen_at'] < r['started_at'] for r in runtimes)
        checks[system + '_options_and_plan'] = all(r['plan_sha256'] == sha(ROOT / 'plan.json') and r['config'] == plan['configs'][system]
            and r['effective_options']['without_timestamps'] == system.endswith('_text') for r in records)
        replay[system] = [r['resumed_records'] for r in runtimes if r['new_records'] == 0]
        if system.endswith('_reference'):
            model = system.split('_')[0]
            historical = read(ROOT / 'historical' / (model + '_baseline.json'))
            def projection(r):
                return [{k: s[k] for k in ('start_sec', 'end_sec', 'raw_asr_text', 'words')} for s in r['segments']]
            checks[system + '_baseline_hypotheses_and_word_times_replayed'] = all(
                r['hypothesis'] == historical[r['id']]['hypothesis'] and projection(r) == projection(historical[r['id']]) for r in records)
        else:
            checks[system + '_tail_decisions_audited'] = all(r.get('backend_audit', {}).get('vad_only_finalization_samples') == 16000 for r in records)
    cpu = {}
    for system in ('parent_text', 'augmented_text'):
        output = ROOT / ('cpu-' + system)
        execution = read(output / 'execution.json')
        records = [read(output / 'predictions' / n) for n in execution['prediction_sha256']]
        runtimes = [read(output / n) for n in execution['runtime_sha256']]
        checks[system + '_CPU_hashes'] = len(records) == 4 and all(sha(output / 'predictions' / n) == h for n, h in execution['prediction_sha256'].items())
        checks[system + '_CPU_execution'] = all(r['runtime_failure'] is None for r in records) and all(r['actual_device'] == 'cpu' for r in runtimes)
        cpu[system] = {'records': len(records), 'precision': sorted({r['actual_precision'] for r in runtimes}), 'quality': 'NOT_EVALUATED_CPU_SMOKE'}
    checks['resume_without_ASR_calls'] = 264 in replay['parent_text']
    snapshots = [read(p) for p in ROOT.glob('north55-text-window-fix-*.json')]
    inference = [s for s in snapshots if any(a in s['command'] for a in ('infer', 'cpu'))]
    allowed = {'/app/src', '/app/scripts', '/app/configs', '/app/SPEC.md', '/app/SOURCES.md', '/app/ACCEPTANCE.yaml', '/app/uv.lock',
               '/audio', '/models', '/study/plan.json', '/study/inputs.json', '/study/protocol.md'}
    checks['offline_inference_exit_zero'] = bool(inference) and all(s['network_mode'] == 'none' and s['state']['ExitCode'] == 0 for s in inference)
    checks['inference_cannot_access_references_or_history'] = all({m['Destination'] for m in s['mounts']} <= allowed | {
        '/study/' + ('cpu-' if 'cpu' in s['command'] else '') + s['command'][-1]} for s in inference)
    checks['only_own_output_is_writable'] = all(sum(m['RW'] for m in s['mounts']) == 1 for s in inference)
    suites = [ET.parse(p).getroot() for p in ROOT.glob('tests-*.xml')]
    checks['22_tests_passed'] = any(int(s.get('tests', 0)) == 22 and not int(s.get('failures', 0)) and not int(s.get('errors', 0))
                                  for root in suites for s in root.iter('testsuite'))
    audio_tests = ET.parse(ROOT / 'audio-contract-tests.xml').getroot()
    checks['3_audio_contract_tests_passed'] = any(int(s.get('tests', 0)) == 3 and not int(s.get('failures', 0)) and not int(s.get('errors', 0))
                                               for s in audio_tests.iter('testsuite'))
    serving = read(ROOT / 'serving-status.json')
    checks['serving_baseline_preserved'] = serving['deployment_candidate'] == 'baseline' and serving['model'] == 'small' and serving['validated_scope'] == []
    verification = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks, 'failed': [k for k, v in checks.items() if not v],
                    'resume_records': replay, 'CPU': cpu, 'scope': 'Artifact integrity/execution only; functional repeat safeguard remains FAIL.'}
    save(ROOT / 'verification.json', verification)
    save(ROOT / 'status.json', {'implemented': True, 'executed': True, 'artifact_verification': verification['status'],
        'tail_loop_regression': 'PASS' if checks['tail_loop_mechanically_fixed'] else 'FAIL',
        'repeated_utterance_exact_retention': 'FAIL', 'full_functional_regression': regression['status'],
        'GPU_predictions': 1056, 'CPU_smokes': 8, 'new_training_runs': 0, 'diagnostic_gates': result['gates'],
        'independent_ASR_quality': 'NEEDS_MORE_DATA', 'critical_entities': 'NEEDS_MORE_DATA',
        'NLP': 'NEEDS_MORE_DATA', 'temporal_detection': 'NEEDS_MORE_DATA', 'release_gate': 'FAIL', 'release_promoted': False})
    lines = ['# Исправление повторной обработки хвоста', '',
        '**Цикл лишних проходов исправлен на воспроизводимом примере. Полная функциональная проверка — FAIL:** '
        'во второй реально повторённой фразе пропущено слово `him`. Вариант не допущен в release.', '',
        '## Реальная регрессия', '',
        '- Исходная запись 2,27 с: 9 проходов в прежнем text-режиме → 1; фразы `Thank you for watching` исчезли.',
        '- Две копии с паузой 1 с: 2 прохода. Второе высказывание присутствует, но не полностью; требование точного сохранения повторов не ослаблено.',
        '- Таймкоды проверены в искусственно заданных координатах +30 с. Это проверка преобразования координат, не человеческий временной эталон.',
        '- Пустой вход не вызывает модель. Изменение не удаляет текстовые повторы и не заменяет числа.', '',
        '## Lexical WER (%)', '',
        '| Набор | Parent baseline | Parent прежний text | Parent исправленный | Augmented baseline | Augmented прежний text | Augmented исправленный |',
        '|---|---:|---:|---:|---:|---:|---:|']
    order = ('parent_reference', 'old_parent_text', 'parent_text', 'augmented_reference', 'old_augmented_text', 'augmented_text')
    for cohort in ('partial_human_dev', 'publisher_weak_dev', 'general_clean', 'general_ru', 'short_general_clean', 'quiet_general_clean', 'quiet_partial_human_dev', 'voici_mix_0dB', 'voici_mix_10dB'):
        c = result['cohorts'][cohort]
        lines.append('| ' + cohort + ' | ' + ' | '.join(f'{100*c["systems"][s]["counts"]["wer_lexical_corpus"]:.2f}' for s in order) + ' |')
    lines += ['', '## Сравнение с корректным baseline', '']
    for model in ('parent', 'augmented'):
        c = result['cohorts']['partial_human_dev']['comparisons'][model + '_vs_baseline']
        ci = c['bootstrap']
        lines.append(f'- {model}: относительное снижение WER {100*c["relative_reduction"]:.2f}%; '
                     f'95% CI ΔWER [{100*ci["lower"]:.2f}; {100*ci["upper"]:.2f}] п.п. Gates: {json.dumps(result["gates"][model])}.')
    lines += ['', 'Улучшение относительно сломанного text-режима не подменяет требуемое улучшение относительно baseline.', '',
        '## Шум: вставленные слова/мин', '', '| Набор | Parent baseline | Parent прежний text | Parent исправленный | Augmented baseline | Augmented прежний text | Augmented исправленный |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for cohort in ('noise_only', 'bleriot_b_noise'):
        c = result['cohorts'][cohort]
        lines.append('| ' + cohort + ' | ' + ' | '.join(f'{c["systems"][s]["inserted_words_per_minute"]:.3f}' for s in order) + ' |')
    lines += ['', '## Проверки и ограничения', '',
        f'- 1056 новых GPU-ответов, 8 CPU smoke; runtime failures: {result["runtime_failures"]}. '
        f'Артефакты: {verification["status"]}, {len(checks)} проверок; 25 тестов (22 в замороженном наборе и 3 дополнительных проверки входного аудио).',
        '- 528 свежих baseline-ответов сверены с прежними текстами и таймкодами. Checkpoint, precision, baseline и эталоны сохранены.',
        '- Каждый исправленный ответ содержит внутренние VAD-интервалы и решения о продвижении курсора. '
        'Начальное окно сохраняет полный контекст; повторный проход начинается перед следующим обнаруженным началом речи.',
        '- VAD/выравнивание могут пропустить тихое начало или непрерывный повтор. Критические команды и сущности в достаточном объёме не проверены.',
        '- Пять кабинных dev-фрагментов: 115 слов, 3 группы, ранее использованные данные. Независимый ASR/сущности/NLP/temporal gate: NEEDS_MORE_DATA.',
        '- RU измерен на общей речи; качество RU/mixed в кабине не доказано. Ни один новый checkpoint не обучался.',
        '- Прототип v1 потерял повтор целиком; v2/v3 не устранили хвост. Эти отрицательные результаты сохранены. '
        'Полное сравнение было выполнено у v1 и v4; v2/v3 остановились на механической проверке.',
        '- Четыре пары прототипов консервативно учтены: 22 → 30 конфигураций. Пороги ACCEPTANCE не менялись.',
        '- Рабочий сервис остаётся на обычном small/CPU int8/baseline. Исследовательский text-адаптер не активирован.',
        '', 'Команды и устройство исправления: `docs/text_window_fix.md`.', '']
    (ROOT / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'verification': verification['status'], 'checks': len(checks), 'failed': verification['failed'],
                      'full_functional_regression': regression['status'], 'release_gate': 'FAIL'}))
    if verification['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except PermissionError:
        if '--in-container' in sys.argv:
            raise
        args = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python']
        mounts = [(ROOT, '/app/reports/text-window-fix-v4', False), (Path(__file__).resolve(), '/app/scripts/report_text_window_fix.py', True),
                  (REPO / 'reports/decoding-v1', '/app/reports/decoding-v1', True),
                  *[(REPO / n, '/app/' + n, True) for n in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml',
                      'data/curated/language-large-v1/scoring/references.json')]]
        for local, remote, readonly in mounts:
            args += ['-v', f'{local.as_posix()}:{remote}' + (':ro' if readonly else '')]
        args += ['north55-speech-gpu:0.1.0', '/app/scripts/report_text_window_fix.py', '--in-container']
        raise SystemExit(subprocess.run(args, check=False).returncode) from None
