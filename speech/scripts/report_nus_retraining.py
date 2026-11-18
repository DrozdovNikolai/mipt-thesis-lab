"""Verify NUS training/execution evidence and report actual diagnostic metrics."""

import hashlib
import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/nus-training-v1'


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def manifest(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def main():
    evaluation = ROOT / 'evaluation-v2'
    plan, ev, result = read(ROOT / 'plan.json'), read(evaluation / 'plan.json'), read(evaluation / 'comparison.json')
    trained, prepared = read(ROOT / 'training.json'), read(ROOT / 'preparation.json')
    old_plan = read(REPO / 'reports/balanced-v1/plan.json')
    old_trained = read(REPO / 'reports/balanced-v1/training.json')
    old = manifest(REPO / 'data/curated/balanced-v1/train.jsonl')
    current = manifest(REPO / 'data/curated/nus-training-v1/train.jsonl')
    support = [row for row in current if row['scope'] == 'general_control']
    nus = [row for row in current if row['source_dataset'] == 'NUS-SIA/CDE4301-VR-401']
    items = read(evaluation / 'inputs.json')
    checks = {
        'all_frozen_sources_unchanged': all(sha(ROOT / 'frozen' / name) == value
            for name, value in read(ROOT / 'frozen-files.json').items()),
        'prior_user_annotations_contracts_and_reports_preserved': all(sha(REPO / name) == value
            for name, value in read(REPO / 'reports/balanced-v1/protected-before.json').items()),
        'old_balanced_train_manifest_preserved': sha(REPO / 'data/curated/balanced-v1/train.jsonl') == old_plan['train_sha256'],
        'new_train_identity': sha(REPO / 'data/curated/nus-training-v1/train.jsonl') == plan['train_sha256'] == trained['train_sha256'],
        'old_dev_byte_identical': sha(REPO / 'data/curated/nus-training-v1/dev.jsonl') == plan['dev_sha256'] == trained['dev_sha256'] == old_plan['dev_sha256'],
        'permission_evidence_recorded': sha(ROOT / 'permission.json') == plan['permission_sha256'] == plan['config']['permission_evidence_sha256'],
        'permission_does_not_claim_public_license': read(ROOT / 'permission.json')['public_license_found'] is False,
        'same_original_transformers_parent': trained['base_manifest'] == old_trained['base_manifest'] == plan['base_manifest'],
        'one_fixed_checkpoint_240': trained['training_coverage']['global_optimizer_steps'] == 240
            and trained['training_coverage']['selected_checkpoint'].endswith('checkpoint-240'),
        'all_675_training_examples_loaded': trained['training_coverage']['unique_samples_loaded'] == len(current) == 675
            and set(trained['training_coverage']['sample_load_counts']) == {row['sample_id'] for row in current},
        'finite_train_and_dev_loss': math.isfinite(trained['train_metrics']['train_loss']) and math.isfinite(trained['dev_metrics']['eval_loss']),
        'training_config_matches': trained['config'] == plan['config'],
        'converted_GPU_smoke': trained['converted_inference'] == 'executed',
        '400_general_support_rows_unchanged': support == [row for row in old if row['scope'] == 'general_control'] and len(support) == 400,
        'NUS_275_weak_unknown_scope_train_only': len(nus) == 275 and all(row['transcript_status'] == 'weak'
            and row['split'] == 'train' and row['scope'] == 'unknown' and not row['scope_verified']
            and not row['primary'] and not row['speaker_ids'] for row in nus),
        'NUS_one_conservative_group': len({row['group_id'] for row in nus}) == 1,
        'no_manufactured_origin_times': all(row['annotation_provenance']['source_interval_known'] is False
            and row['annotation_provenance']['source_start_sec'] is None
            and row['annotation_provenance']['source_end_sec'] is None for row in nus),
        '38_unique_exclusions_preserved': len(read(ROOT / 'exclusions.json')) == prepared['excluded_unique'] == 38,
        'no_weak_BLeRIOT_train_pairs_retained': len(current) == len(support) + len(nus),
        'preparation_identity': sha(ROOT / 'preparation.json') == plan['preparation_sha256'],
        'frozen_evaluation_inputs_match_old': len(items) == 675
            and sha(evaluation / 'inputs.json') == plan['inputs_sha256'] == ev['inputs_sha256'] == old_plan['inputs_sha256'],
        'same_frozen_protocol': sha(ROOT / 'protocol.md') == plan['protocol_sha256'] == ev['protocol_sha256'] == sha(evaluation / 'protocol.md'),
        'eval_training_plan_link': ev['training_plan_sha256'] == sha(ROOT / 'plan.json'),
        'result_plan_link': result['plan_sha256'] == sha(evaluation / 'plan.json'),
        'scorer_frozen_before_training': read(ROOT / 'scoring-identity.json')['recorded_at_before_training'] < plan['frozen_at'],
        'scorer_snapshot_matches_executed': sha(ROOT / 'frozen/scripts/score_nus_retraining.py')
            == read(ROOT / 'scoring-identity.json')['script_sha256'] == result['report_scorer_sha256'],
        '2025_scored_records': len(read(evaluation / 'scored-counts.json')) == 2025,
        'trained_weights_match_evaluation': trained['converted_model'] == ev['models']['nus']['manifest'],
        'no_final_test_or_release_promotion': not result['test_accessed'] and not result['release_promoted'] and not plan['selection_allowed'],
    }
    previous_ev = read(REPO / 'reports/balanced-v1/evaluation/plan.json')
    for system in ('parent', 'balanced'):
        path = evaluation / 'historical' / (system+'.json')
        checks[system+'_historical_identity'] = sha(path) == ev['historical_sha256'][system] and len(read(path)) == 675
        checks[system+'_checkpoint_preserved'] = ev['models'][system] == previous_ev['models'][system]
    for system, count in (('nus', 675), ('cpu-nus', 4)):
        output = evaluation / system
        execution = read(output / 'execution.json')
        records = [read(output / 'predictions' / name) for name in execution['prediction_sha256']]
        runtimes = [read(output / name) for name in execution['runtime_sha256']]
        checks[system+'_complete_population_and_hashes'] = len(records) == count and all(
            sha(output / 'predictions' / name) == value for name, value in execution['prediction_sha256'].items()) and all(
            sha(output / name) == value for name, value in execution['runtime_sha256'].items())
        checks[system+'_no_runtime_failure'] = all(record['runtime_failure'] is None for record in records)
        expected = ('cpu', 'int8_float32') if system.startswith('cpu') else ('cuda', 'float16')
        checks[system+'_actual_device_precision'] = all((row['actual_device'], row['actual_precision']) == expected for row in runtimes)
        checks[system+'_frozen_before_inference'] = all(ev['frozen_at'] < row['started_at'] for row in runtimes)
        if system == 'nus':
            checks['linux_resume_all675_without_ASR'] = any(row['resumed_records'] == 675 and row['new_records'] == 0 for row in runtimes)
        else:
            checks['CPU_speech_outputs_nonempty'] = all(record['hypothesis'].strip() for record in records if record['cohort'] != 'noise_only')
    snapshots = [read(path) for path in ROOT.glob('north55-nus-v1-*.json')]
    checks['all_stages_offline'] = bool(snapshots) and all(row['network_mode'] == 'none' for row in snapshots)
    failed_attempts = [row['name'] for row in snapshots if row['state']['ExitCode'] != 0]
    amendment = read(ROOT / 'runtime-amendment.json')
    checks['single_preflight_error_preserved_and_resolved'] = failed_attempts == [amendment['failed_attempt']] and any(
        row['command'][-1] == 'freeze-eval' and row['state']['ExitCode'] == 0 for row in snapshots)
    retry = read(ROOT / 'cuda-runtime-retry.json')
    checks['all_675_failed_CUDA_attempts_preserved'] = retry['failed_prediction_count'] == 675 and all(
        sha(ROOT / 'evaluation' / name) == value for name, value in retry['preserved_original_hashes'].items())
    checks['runtime_retry_same_frozen_plan'] = retry['original_plan_sha256'] == retry['retry_plan_sha256'] == sha(evaluation / 'plan.json')
    libraries = read(ROOT / 'runtime-library-versions.json')
    checks['historical_and_new_ASR_CUDA_libraries_match'] = libraries['identical'] and (
        libraries['records'][0]['versions'] == libraries['records'][1]['versions'])
    training = [row for row in snapshots if row['command'][-1] == 'train']
    checks['one_training_run'] = len(training) == 1
    checks['training_no_eval_references_or_history'] = all(not any(m['Destination'].startswith(('/eval', '/scoring', '/previous-eval')) for m in row['mounts']) for row in training)
    inference = [row for row in snapshots if row['command'][-1] in ('infer', 'cpu')]
    allowed = {'/app/src', '/app/scripts', '/app/configs', '/app/SPEC.md', '/app/SOURCES.md',
               '/app/ACCEPTANCE.yaml', '/app/uv.lock', '/audio', '/models',
               '/eval/plan.json', '/eval/inputs.json', '/eval/protocol.md'}
    checks['inference_no_references_or_old_answers'] = all({m['Destination'] for m in row['mounts']} <=
        allowed | {'/eval/' + ('nus' if row['command'][-1] == 'infer' else 'cpu-nus')} for row in inference)
    checks['inference_only_own_output_writable'] = all(sum(m['RW'] for m in row['mounts']) == 1 for row in inference)
    suites = [ET.parse(path).getroot() for path in ROOT.glob('tests-*.xml')]
    checks['43_contract_tests_passed'] = any(int(suite.get('tests', 0)) == 43 and all(int(suite.get(key, 0)) == 0
        for key in ('failures', 'errors', 'skipped')) for root in suites for suite in root.iter('testsuite'))
    runtime = read(ROOT / 'application-runtime.json')
    checks['serving_baseline_preserved'] = runtime['deployment_candidate'] == 'baseline' and runtime['model'] == 'small' and runtime['validated_scope'] == []
    verification = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
                    'failed': [key for key, passed in checks.items() if not passed],
                    'audited_failed_attempts': failed_attempts,
                    'scope': 'Artifact integrity and completed execution after documented preflight repair; not ASR quality certification'}
    save(ROOT / 'verification.json', verification)
    status = {'implemented': True, 'executed': True, 'verified_artifacts': verification['status'],
        'GPU_training_runs': 1, 'GPU_predictions': 675, 'failed_GPU_attempts_preserved': 675,
        'CPU_smokes': 4, 'tests_passed': 43,
        'source_rights_basis': 'explicit_user_confirmation', 'public_license_found': False,
        'diagnostic_gates': result['gates'], 'independent_ASR': 'NEEDS_MORE_DATA',
        'critical_entities': 'NEEDS_MORE_DATA', 'NLP': 'NEEDS_MORE_DATA',
        'temporal_detection': 'NEEDS_MORE_DATA', 'release_gate': result['gates']['parent']['release'],
        'release_promoted': False}
    save(ROOT / 'status.json', status)
    lines = ['# NUS: одно выполненное переобучение Whisper-small', '',
        f'Проверка артефактов: **{verification["status"]}** (проверок: {len(checks)}). '
        f'Release gate: **{status["release_gate"]}**. Рабочая модель сохранена.', '',
        'Основание использования NUS — явное подтверждение пользователя «можно можно обучать, делай», '
        'сохранённое в [permission.json](permission.json). Публичная лицензия не обнаружена; '
        'новое разрешение авторов и право публичного распространения не заявляются.', '',
        '## Данные и обучение', '',
        f'- 275 NUS-пар, {prepared["NUS_minutes"]:.2f} мин. Из 313 уникальных исключены 38: '
        '11 конфликтов текстов и 29 текстовых признаков радиообмена, два клипа относятся к обеим причинам.',
        '- Исходные тексты оставлены без исправлений. Все NUS — weak, scope unknown, одна train-группа; '
        'таймкоды оригинала неизвестны. Проверки scope по аудио не было; фильтр не гарантирует удаления всего ATC.',
        f'- Добавлены прежние 200 EN / 200 RU general-speech пары; всего {prepared["pairs"]} пар, '
        f'{prepared["minutes"]:.2f} мин. 33 слабые BLeRIOT train-пары удалены только из новой смеси. '
        'Оригинальные манифесты сохранены; прежние 35 weak dev-пар совпадают побайтно.',
        '- Исходный Transformers checkpoint, rank 8, seed 55, LR 0.00005, 240 шагов; '
        'единственный checkpoint-240 зафиксирован до обучения. Изменились данные, LR и число шагов: '
        'это один рецепт обучения, а не чистый эксперимент только с составом данных.',
        f'- GPU: {trained["gpu"]}; train loss {trained["train_metrics"]["train_loss"]:.6f}, '
        f'dev loss {trained["dev_metrics"]["eval_loss"]:.6f}. Все {len(current)} примеров загружены. '
        'Loss не является WER и не доказывает улучшение речи.',
        '- Адаптер сохранён, слит с базой, конвертирован в CT2 float16; реальный smoke сохранённых весов выполнен.', '',
        '## Lexical WER (%)', '',
        '| Набор | Исходная модель | Прежняя balanced LoRA | NUS LoRA |', '|---|---:|---:|---:|']
    for cohort in ('partial_human_dev', 'general_clean', 'general_ru', 'publisher_weak_dev',
                   'voici_mix_0dB', 'voici_mix_10dB', 'short_general_clean', 'quiet_general_clean', 'quiet_partial_human_dev'):
        value = result['cohorts'][cohort]
        lines.append('| '+cohort+' | '+' | '.join(f'{100*value["scores"][s]["wer_lexical_corpus"]:.2f}' for s in ('parent', 'balanced', 'nus'))+' |')
    lines += ['', 'Все наборы — ранее открытые dev/controls, не независимый final test. '
        '275 обучающих NUS-клипов в эту оценку не включались. Weak publisher/mix значения '
        'означают расхождение с автоматической привязкой, а не точность относительно подтверждённого эталона.', '',
        '## Кабинный dev, статистика и шум', '']
    cohort = result['cohorts']['partial_human_dev']
    for system in ('parent', 'balanced', 'nus'):
        value = cohort['scores'][system]
        lines.append(f'- {system}: S={value["S"]}, D={value["D"]}, I={value["I"]}, N={value["N"]}.')
    comparison = cohort['comparisons']['parent']
    ci = comparison['bootstrap']
    lines += [f'- Относительное снижение WER против исходной модели: {100*comparison["relative_reduction"]:.2f}%. '
        f'95% cluster bootstrap CI для ΔWER: [{100*ci["lower"]:.2f}; {100*ci["upper"]:.2f}] п.п. '
        '2000 повторов, seed 55. Пять человеческих фрагментов, три группы; результат exploratory.', '']
    for name in ('noise_only', 'bleriot_b_noise'):
        values = result['cohorts'][name]['inserted_words_per_minute']
        lines.append(f'- {name}, вставок/мин: ' + '; '.join(f'{s}={values[s]:.3f}' for s in ('parent', 'balanced', 'nus')) + '.')
    lines += ['', '## Gate', '', '```json', json.dumps(result['gates']['parent'], indent=2), '```', '',
        '- Независимые ASR, критические сущности, NLP и temporal detection: NEEDS_MORE_DATA. '
        'Нет новых human event labels и нет подтверждённого качества RU/mixed cockpit speech.',
        '- 675 новых GPU-ответов, 1350 исторических с проверкой hashes; одинаковые аудио, язык входа '
        'и effective decoder options, CUDA float16. Checkpoint после обучения отличается: '
        'это ASR adaptation, не same-checkpoint pipeline gain.',
        '- Четыре CPU int8 smoke проверяют работоспособность; Linux resume переиспользовал все 675 ответов. '
        'Inference не получал эталоны, старые ответы или train-тексты. Все стадии — network none.',
        '- Runtime failures: '+json.dumps(result['runtime_failures'])+'.',
        '- Один первоначальный freeze-eval завершился ошибкой отсутствующего PyArrow до inference. '
        'Для driver-стадий выбран имеющийся полный training image с теми же версиями ASR библиотек; '
        'код, модель, протокол и scorer сохранены. Отказ и исправление: [runtime-amendment.json](runtime-amendment.json).',
        '- Первый полный GPU-прогон содержал 675 ошибок загрузки libcublas.so.12. Они и его FAIL-отчёт '
        'сохранены в evaluation/. После указания пути к установленным CUDA-библиотекам тот же '
        'план выполнен в evaluation-v2/. Первые четыре успешных CPU smoke переиспользованы. '
        'Обучение не повторялось, результаты не перезаписывались: [cuda-runtime-retry.json](cuda-runtime-retry.json).',
        '- Candidate не продвинут в release. Пороги, исходные SPEC/SOURCES/ACCEPTANCE и baseline сохранены.', '',
        'Команды и ограничения воспроизведения: [docs/nus_retraining.md](../../docs/nus_retraining.md).',
        'Машинные измерения: [comparison.json](evaluation-v2/comparison.json), [status.json](status.json), '
        '[verification.json](verification.json). Побайтное сравнение пересчёта: '
        '[cross-platform-replay.json](cross-platform-replay.json).', '']
    (ROOT / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'verification': verification, 'status': status}, ensure_ascii=False, indent=2))
    if verification['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except PermissionError:
        if '--in-container' in sys.argv:
            raise
        args = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
                '-v', f'{REPO.as_posix()}:/app:ro',
                '-v', f'{ROOT.as_posix()}:/app/reports/nus-training-v1',
                'north55-speech-gpu:0.1.0',
                '/app/scripts/report_nus_retraining.py', '--in-container']
        raise SystemExit(subprocess.run(args, check=False).returncode) from None
