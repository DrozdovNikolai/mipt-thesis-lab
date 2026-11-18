"""Verify balanced-training artifacts without deriving a release claim."""

import hashlib
import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/balanced-v1'


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def manifest(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def main():
    evaluation = ROOT / 'evaluation'
    plan, ev, result = read(ROOT / 'plan.json'), read(evaluation / 'plan.json'), read(evaluation / 'comparison.json')
    trained, prepared = read(ROOT / 'training.json'), read(ROOT / 'preparation.json')
    original = manifest(REPO / 'data/curated/retraining-v1/augmented/train.jsonl')
    current = manifest(REPO / 'data/curated/balanced-v1/train.jsonl')
    items = read(evaluation / 'inputs.json')
    expected_inputs = [{**i, 'reference_id': i['id'], 'gain_db': 0.} for i in read(REPO / 'reports/retraining-v1/inputs.json')]
    expected_inputs += [i for i in read(REPO / 'reports/decoding-v1/inputs.json') if i['gain_db']]
    old_plan = read(REPO / 'reports/retraining-v1/plan.json')
    old_trained = read(REPO / 'reports/retraining-v1/augmented-training.json')
    def en(row):
        return row['source_dataset'] == 'openslr/librispeech_asr' and row['language'] == 'en'
    protected_unchanged = all(a == b for a, b in zip(original, current, strict=True) if not en(a))
    def comparable(c):
        return {k: v for k, v in c.items() if k not in ('train_manifest', 'output')}
    checks = {
        'all_frozen_sources': all(sha(ROOT / 'frozen' / n) == h for n, h in read(ROOT / 'frozen-files.json').items()),
        'protected_user_data_and_old_reports': all(sha(REPO / n) == h for n, h in read(ROOT / 'protected-before.json').items()),
        'plan_train_hash': sha(REPO / 'data/curated/balanced-v1/train.jsonl') == plan['train_sha256'] == trained['train_sha256'],
        'original_dev_byte_identical': sha(REPO / 'data/curated/balanced-v1/dev.jsonl') == plan['dev_sha256'] == trained['dev_sha256'] == old_plan['data']['augmented']['dev_sha256'],
        'same_training_implementation': sha(ROOT / 'frozen/src/north55_speech/lora.py') == sha(REPO / 'reports/retraining-v1/frozen/src/north55_speech/lora.py'),
        'same_training_config_except_EN_manifest_output': comparable(plan['config']) == comparable(old_plan['configs']['augmented']),
        'training_report_matches_config': trained['config'] == plan['config'],
        'same_parent_checkpoint': trained['base_manifest'] == old_trained['base_manifest'] == plan['base_manifest'],
        'one_fixed_checkpoint_120': trained['training_coverage']['global_optimizer_steps'] == 120 and trained['training_coverage']['selected_checkpoint'].endswith('checkpoint-120'),
        'all_433_samples_loaded': trained['training_coverage']['unique_samples_loaded'] == 433 and set(trained['training_coverage']['sample_load_counts']) == {s['sample_id'] for s in current},
        'finite_train_dev_loss': math.isfinite(trained['train_metrics']['train_loss']) and math.isfinite(trained['dev_metrics']['eval_loss']),
        'converted_GPU_smoke': trained['converted_inference'] == 'executed',
        'RU_weak_rows_and_order_unchanged': protected_unchanged and sum(not en(r) for r in current) == 233,
        'protected_records_same_loader_visits': all(trained['training_coverage']['sample_load_counts'][r['sample_id']] == old_trained['training_coverage']['sample_load_counts'][r['sample_id']] for r in current if not en(r)),
        '200_EN_and_19_speakers': sum(en(r) for r in current) == 200 and len({v for r in current if en(r) for v in r['speaker_ids']}) == 19,
        'complete_frozen_input_population': len(items) == 675 and sha(evaluation / 'inputs.json') == plan['inputs_sha256'] == ev['inputs_sha256'],
        'all_existing_661_and_14_quiet_inputs_unchanged': items == expected_inputs,
        'same_frozen_protocol': sha(ROOT / 'protocol.md') == plan['protocol_sha256'] == ev['protocol_sha256'] == sha(evaluation / 'protocol.md'),
        'training_eval_plan_link': ev['training_plan_sha256'] == sha(ROOT / 'plan.json'),
        'result_plan_link': result['plan_sha256'] == sha(evaluation / 'plan.json'),
        'scorer_snapshot_identity': sha(ROOT / 'scoring/score_balanced_retraining.py') == read(ROOT / 'scoring/identity.json')['script_sha256'] == result['report_scorer_sha256'],
        'scorer_recorded_before_evaluation': read(ROOT / 'scoring/identity.json')['recorded_at_before_evaluation'] < ev['frozen_at'],
        'all_2025_scored_records': len(read(evaluation / 'scored-counts.json')) == 2025,
        'same_new_converted_weights': trained['converted_model'] == ev['models']['balanced']['manifest'],
        'preparation_report_identity': sha(ROOT / 'preparation.json') == plan['preparation_sha256'],
        'no_final_test_or_promotion': not result['test_accessed'] and not result['release_promoted'] and not plan['selection_allowed'],
    }
    for system in ('parent', 'augmented'):
        history = evaluation / 'historical' / (system+'.json')
        checks[system+'_675_historical_hashes'] = sha(history) == ev['historical_sha256'][system] and len(read(history)) == 675
        checks[system+'_old_checkpoint_preserved'] = ev['models'][system] == read(REPO / 'reports/retraining-v1/evaluation/plan.json')['models'][system]
    resumes = []
    for system, count in (('balanced', 675), ('cpu-balanced', 4)):
        output = evaluation / system
        execution = read(output / 'execution.json')
        records = [read(output / 'predictions' / name) for name in execution['prediction_sha256']]
        runtimes = [read(output / name) for name in execution['runtime_sha256']]
        checks[system+'_hashes_and_population'] = len(records) == count and all(sha(output / 'predictions' / n) == h for n, h in execution['prediction_sha256'].items()) and all(sha(output / n) == h for n, h in execution['runtime_sha256'].items())
        checks[system+'_no_runtime_failure'] = all(r['runtime_failure'] is None for r in records)
        expected = ('cpu', 'int8_float32') if system.startswith('cpu') else ('cuda', 'float16')
        checks[system+'_actual_device_precision'] = all((r['actual_device'], r['actual_precision']) == expected for r in runtimes)
        checks[system+'_frozen_before_inference'] = all(ev['frozen_at'] < r['started_at'] for r in runtimes)
        if system == 'balanced':
            resumes = [r['resumed_records'] for r in runtimes if r['new_records'] == 0]
        else:
            checks['CPU_speech_outputs_nonempty'] = all(r['hypothesis'].strip() for r in records if r['cohort'] != 'noise_only')
    checks['resume_all675_without_ASR'] = 675 in resumes
    snapshots = [read(p) for p in ROOT.glob('north55-balanced-v1-*.json')]
    checks['all_stage_executions_offline_exit0'] = bool(snapshots) and all(s['network_mode'] == 'none' and s['state']['ExitCode'] == 0 for s in snapshots)
    training = [s for s in snapshots if s['command'][-1] == 'train']
    old_snapshot = read(REPO / 'reports/retraining-v1/north55-retraining-v1-train-augmented.json')
    checks['one_training_same_image'] = len(training) == 1 and training[0]['image_id'] == old_snapshot['image_id']
    checks['training_no_final_references_or_history'] = all(not any(m['Destination'].startswith(('/eval', '/scoring', '/previous-eval', '/quiet-history')) for m in s['mounts']) for s in training)
    inference = [s for s in snapshots if s['command'][-1] in ('infer', 'cpu')]
    allowed = {'/app/src', '/app/scripts', '/app/configs', '/app/SPEC.md', '/app/SOURCES.md', '/app/ACCEPTANCE.yaml', '/app/uv.lock', '/audio', '/models', '/eval/plan.json', '/eval/inputs.json', '/eval/protocol.md'}
    checks['inference_isolated_from_references_and_old_answers'] = all({m['Destination'] for m in s['mounts']} <= allowed | {'/eval/' + ('balanced' if s['command'][-1] == 'infer' else 'cpu-balanced')} for s in inference)
    checks['inference_only_own_output_writable'] = all(sum(m['RW'] for m in s['mounts']) == 1 for s in inference)
    suites = [ET.parse(p).getroot() for p in ROOT.glob('tests-*.xml')]
    checks['26_contract_tests_passed'] = any(int(s.get('tests', 0)) == 26 and not int(s.get('failures', 0)) and not int(s.get('errors', 0)) for root in suites for s in root.iter('testsuite'))
    runtime = read(ROOT / 'application-runtime.json')
    checks['serving_baseline_preserved'] = runtime['deployment_candidate'] == 'baseline' and runtime['model'] == 'small' and runtime['validated_scope'] == []
    verification = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
        'failed': [k for k, v in checks.items() if not v], 'scope': 'Artifact integrity and execution, not quality certification'}
    save(ROOT / 'verification.json', verification)
    status = {'implemented': True, 'executed': True, 'verified_artifacts': verification['status'],
        'GPU_training_runs': 1, 'GPU_predictions': 675, 'CPU_smokes': 4, 'tests_passed': 26,
        'diagnostic_gates': result['gates'], 'independent_ASR': 'NEEDS_MORE_DATA', 'critical_entities': 'NEEDS_MORE_DATA',
        'NLP': 'NEEDS_MORE_DATA', 'temporal_detection': 'NEEDS_MORE_DATA',
        'release_gate': result['gates']['parent']['release'], 'release_promoted': False}
    save(ROOT / 'status.json', status)
    lines = ['# Один опыт с равномерной EN-выборкой', '',
        f'Реализация и исполнение завершены. Проверки артефактов: **{verification["status"]}** ({len(checks)}). '
        f'Release gate: **{status["release_gate"]}**; рабочий baseline сохранён.', '',
        '## Данные и обучение', '',
        f'- 200 EN записей от 19 дикторов вместо двух; 233 RU/weak записи и их позиции сохранены. Всего 433 пары, {prepared["minutes"]:.2f} мин.',
        f'- EN длительность: {prepared["old_EN_support_minutes"]:.2f} → {prepared["EN_support_minutes"]:.2f} мин. С прежним EN-пакетом совпадают {prepared["new_EN_overlap_with_old_selection"]} записей.',
        '- В большинстве групп по 10–11 EN-записей, у самого малого диктора 8. Поменялись также фразы и длительности: это проверка политики отбора, не чистого эффекта числа дикторов.',
        '- Та же реализация обучения и Docker image, исходный checkpoint, rank 8, LR 0.0001, seed 55 и 120 шагов. Конечный checkpoint-120 выбран заранее; все 433 записи загружены.',
        '- Тексты взяты из разрешённого корпуса без новой ручной разметки. Кабинные пары остаются weak; NLP/сущности/временные события не созданы.', '',
        '## Lexical WER (%)', '', '| Набор | Исходная модель | Прежняя LoRA | Новая LoRA |', '|---|---:|---:|---:|']
    for cohort in ('partial_human_dev', 'general_clean', 'general_ru', 'publisher_weak_dev', 'voici_mix_0dB', 'voici_mix_10dB', 'short_general_clean', 'quiet_general_clean', 'quiet_partial_human_dev'):
        c = result['cohorts'][cohort]
        lines.append('| '+cohort+' | '+' | '.join(f'{100*c["scores"][s]["wer_lexical_corpus"]:.2f}' for s in ('parent', 'augmented', 'balanced'))+' |')
    lines += ['', 'Слабые издательские эталоны и смеси измеряют расхождение с привязкой, а не независимую точность.', '', '## Кабинный dev и статистика', '']
    c = result['cohorts']['partial_human_dev']
    for system in ('parent', 'augmented', 'balanced'):
        s = c['scores'][system]
        lines.append(f'- {system}: S={s["S"]}, D={s["D"]}, I={s["I"]}, N={s["N"]}.')
    for system in ('parent', 'augmented'):
        comp = c['comparisons'][system]
        ci = comp['bootstrap']
        lines.append(f'- Относительно {system}: снижение WER {100*comp["relative_reduction"]:.2f}%; 95% CI ΔWER [{100*ci["lower"]:.2f}; {100*ci["upper"]:.2f}] п.п. Статистическая проверка: {result["gates"][system]["statistical_confirmation"]}.')
    lines += ['', '## Ложные слова на шуме', '', '| Набор | Исходная, слов/мин | Прежняя LoRA | Новая LoRA |', '|---|---:|---:|---:|']
    for cohort in ('noise_only', 'bleriot_b_noise'):
        c = result['cohorts'][cohort]
        lines.append('| '+cohort+' | '+' | '.join(f'{c["inserted_words_per_minute"][s]:.3f}' for s in ('parent', 'augmented', 'balanced'))+' |')
    lines += ['', '## Проверки и ограничения', '',
        '- 675 новых GPU-ответов и 1350 сохранённых reference-ответов, проверенных по хешам. Историческое время не сравнивается со свежим. Обычное декодирование, одинаковая CUDA float16 и параметры кроме checkpoint.',
        '- 4 CPU int8 smoke — исполнение, не точность. Повторный GPU запуск переиспользовал все 675 ответов без ASR. Runtime failures: '+json.dumps(result['runtime_failures'])+'.',
        '- 26 тестов контрактов прошли. Приёмка качества отдельно от этих тестов: '+json.dumps(result['gates']['parent'])+'.',
        '- Пять ранее использованных кабинных dev-фрагментов: 115 слов и 3 группы. Счётчики пропусков и повторённых триграмм сохранены в evaluation/human-error-counts.json; повторы могут быть реально произнесены, текст не очищался.',
        '- Independent ASR/critical entities/NLP/temporal: NEEDS_MORE_DATA. RU — общая читаемая речь; кабинный RU и mixed не подтверждены. Новая LoRA не доказывает same-checkpoint pipeline gain.',
        '- Пороги и старые результаты сохранены. Один новый опыт учтён отдельно: 30 → 31 конфигурация, без нового подбора.',
        '', 'Команды и checklist: docs/balanced_retraining.md.', '']
    (ROOT / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'verification': verification['status'], 'checks': len(checks), 'failed': verification['failed'], 'release_gate': status['release_gate']}))
    if verification['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except PermissionError:
        if '--in-container' in sys.argv:
            raise
        args = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python']
        mounts = [(ROOT, '/app/reports/balanced-v1', False),
            (Path(__file__).resolve(), '/app/scripts/report_balanced_retraining.py', True),
            (REPO / 'reports/retraining-v1', '/app/reports/retraining-v1', True),
            (REPO / 'reports/text-window-fix-v4', '/app/reports/text-window-fix-v4', True),
            (REPO / 'reports/decoding-v1/inputs.json', '/app/reports/decoding-v1/inputs.json', True),
            (REPO / 'data/curated', '/app/data/curated', True),
            *[(REPO / n, '/app/'+n, True) for n in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml')]]
        for source, target, ro in mounts:
            args += ['-v', f'{source.as_posix()}:{target}' + (':ro' if ro else '')]
        args += ['north55-speech-gpu:0.1.0', '/app/scripts/report_balanced_retraining.py', '--in-container']
        raise SystemExit(subprocess.run(args, check=False).returncode) from None
