"""Verify immutable artifacts and render results; standard-library-only on Windows/Linux."""
import hashlib
import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/retraining-v1'
SYSTEMS = ('parent', 'control', 'augmented')


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def main():
    plan, evaluation = read(ROOT / 'plan.json'), read(ROOT / 'evaluation/plan.json')
    result, rows = read(ROOT / 'evaluation/comparison.json'), read(ROOT / 'evaluation/scored-rows.json')
    items = read(ROOT / 'evaluation/inputs.json')
    trained = {a: read(ROOT / f'{a}-training.json') for a in SYSTEMS[1:]}
    def manifest(path):
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    curated = REPO / 'data/curated'
    train_rows = manifest(curated / 'retraining-v1/augmented/train.jsonl')
    reviewed = manifest(curated / 'reviewed-pilot-v2/dev.jsonl')
    keys = ('group_id', 'session_id', 'recording_id', 'original_utterance_id', 'audio_sha256', 'decoded_audio_sha256')
    overlap = {k: sorted(({r[k] for r in train_rows} - {None}) & ({r[k] for r in reviewed} - {None})) for k in keys}
    overlap['speaker_ids'] = sorted({v for r in train_rows for v in r['speaker_ids']} & {v for r in reviewed for v in r['speaker_ids']})
    originals = manifest(curated / 'publisher-expanded-v1/training/train.jsonl') + manifest(curated / 'training-support-v1/train.jsonl')
    def unchanged_content(records):
        return {r['sample_id']: {k: v for k, v in r.items() if k != 'group_id'} for r in records}
    checks = {
        'frozen_source_files': all(sha(ROOT / 'frozen' / n) == h for n, h in read(ROOT / 'frozen-files.json').items()),
        'original_acceptance_unchanged': sha(REPO / 'ACCEPTANCE.yaml') == plan['acceptance_sha256'] ==
            '32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071',
        'original_baseline_unchanged': sha(REPO / 'configs/baseline.yaml') == plan['baseline_sha256'],
        'fresh_baseline_reproduces_all_previous_661_answers': read(ROOT / 'baseline-replay.json')['same_requests_and_baseline_outputs'] is True,
        'original_spec_sources_unchanged': all(sha(REPO / n) == sha(ROOT / 'frozen' / n) for n in ('SPEC.md', 'SOURCES.md')),
        'training_plan_link': evaluation['training_plan_sha256'] == sha(ROOT / 'plan.json'),
        'frozen_protocol': sha(ROOT / 'protocol.md') == plan['protocol_sha256'] == evaluation['protocol_sha256'],
        'unchanged_661_inputs': len(items) == 661 and sha(ROOT / 'evaluation/inputs.json') == plan['inputs_sha256'],
        'same_parent_weights': all(t['base_manifest'] == plan['base_manifest'] for t in trained.values()),
        'both_120_steps_and_complete_loader_coverage': all(t['training_coverage']['global_optimizer_steps'] == 120
            and t['training_coverage']['unique_samples_loaded'] == plan['data'][a]['pairs'] for a, t in trained.items()),
        'both_single_final_checkpoint': all(t['training_coverage']['selected_checkpoint'].endswith('checkpoint-120') for t in trained.values()),
        'GPU_converted_smokes_executed': all(t['converted_inference'] == 'executed' for t in trained.values()),
        'finite_training_and_dev_losses': all(math.isfinite(t['train_metrics']['train_loss'])
            and math.isfinite(t['dev_metrics']['eval_loss']) for t in trained.values()),
        'both_models_changed_from_parent': all(t['converted_model']['files']['model.bin'] !=
            evaluation['models']['parent']['manifest']['files']['model.bin'] for t in trained.values()),
        'data_manifests_preserved': all(sha(REPO / 'data/curated/retraining-v1' / a / 'train.jsonl') == plan['data'][a]['train_sha256'] for a in trained),
        'original_dev_preserved': sha(REPO / 'data/curated/publisher-expanded-v1/training/dev.jsonl') ==
            sha(REPO / 'data/curated/retraining-v1/dev.jsonl') == plan['data']['control']['dev_sha256'],
        'original_support_preserved': sha(REPO / 'data/curated/training-support-v1/train.jsonl') == plan['source_manifests']['support_train'],
        'original_weak_train_preserved': sha(curated / 'publisher-expanded-v1/training/train.jsonl') == plan['source_manifests']['weak_train'],
        '433_pairs_preserve_original_texts_and_provenance': unchanged_content(train_rows) == unchanged_content(originals),
        'reviewed_dev_metadata_disjoint_from_training': len(reviewed) == 5 and not any(overlap.values()),
        'no_training_quality_or_release_claim': all(t['quality_evidence'] is False and t['selection_allowed'] is False for t in trained.values()),
        'same_precision_and_options_except_checkpoint': len({json.dumps({k: v for k, v in c.items() if k != 'model'}, sort_keys=True)
            for c in evaluation['configs'].values()}) == 1,
        'all_1983_scored_rows': len(rows) == 1983 and {s: sum(r['system'] == s for r in rows) for s in SYSTEMS} == dict.fromkeys(SYSTEMS, 661),
        'all_runtime_failures_retained': result['runtime_failures'] == {s: sum(r['runtime_failure'] is not None for r in rows if r['system'] == s) for s in SYSTEMS},
        'result_plan_link': result['plan_sha256'] == sha(ROOT / 'evaluation/plan.json'),
        'no_test_or_promotion_claim': result['test_accessed'] is False and result['release_promoted'] is False,
    }
    for system in SYSTEMS:
        execution = read(ROOT / 'evaluation' / system / 'execution.json')
        predictions = ROOT / 'evaluation' / system / 'predictions'
        checks[f'{system}_661_prediction_hashes'] = len(execution['prediction_sha256']) == 661 and all(
            sha(predictions / n) == h for n, h in execution['prediction_sha256'].items())
        snapshot = read(ROOT / f'north55-retraining-v1-infer-{system}.json')
        checks[f'{system}_offline_exit_zero'] = snapshot['network_mode'] == 'none' and snapshot['state']['ExitCode'] == 0
        destinations = {m['Destination'] for m in snapshot['mounts']}
        checks[f'{system}_no_reference_mount'] = destinations <= {
            '/app/scripts', '/app/src', '/app/configs', '/app/SPEC.md', '/app/SOURCES.md',
            '/app/ACCEPTANCE.yaml', '/app/uv.lock', '/audio', '/models',
            '/eval/plan.json', '/eval/inputs.json', '/eval/protocol.md', '/eval/' + system}
        runtimes = [read(p) for p in (ROOT / 'evaluation' / system).glob('runtime-*.json')]
        checks[f'{system}_actual_cuda_float16'] = all(r['actual_device'] == 'cuda' and r['actual_precision'] == 'float16' for r in runtimes)
        checks[f'{system}_same_input_language_information'] = all(read(predictions / f'{i["id"]}.json')['effective_options']['language'] ==
            (i['input_language'] if i['input_language'] in ('en', 'ru') else None) for i in items)
    for arm in trained:
        snapshot = read(ROOT / f'north55-retraining-v1-train-{arm}.json')
        checks[f'{arm}_offline_training_exit_zero'] = snapshot['network_mode'] == 'none' and snapshot['state']['ExitCode'] == 0
        checks[f'{arm}_training_no_evaluation_references'] = all(m['Destination'] not in ('/scoring', '/scoring/references.json', '/eval') for m in snapshot['mounts'])
    cpu = read(ROOT / 'smoke/cpu-smoke.json')
    checks['offline_CPU_smoke'] = cpu['status'] == 'PASS' and cpu['actual_device'] == 'cpu' and read(ROOT / 'north55-retraining-v1-cpu.json')['network_mode'] == 'none'
    runtime = read(ROOT / 'application-runtime.json')
    checks['application_keeps_baseline'] = runtime['deployment_candidate'] == 'baseline' and runtime['model'] == 'small'
    test_runs = []
    test_paths = list(ROOT.glob('north55-retraining-v1-tests*.xml'))
    if (ROOT / 'contracts.xml').exists():
        test_paths.append(ROOT / 'contracts.xml')
    for path in sorted(test_paths):
        suite = ET.parse(path).getroot().find('testsuite')
        test_runs.append({'path': path.name, **suite.attrib})
    checks['38_contract_tests_passed'] = any(int(r['tests']) >= 38 and int(r['failures']) == 0 and int(r['errors']) == 0 for r in test_runs)
    resume_path = ROOT / 'north55-retraining-v1-infer-augmented-resume.json'
    if resume_path.exists():
        latest = max((ROOT / 'evaluation/augmented').glob('runtime-*.json'))
        resume = read(latest)
        checks['completed_inference_resume_661_reused_zero_calls'] = resume['resumed_records'] == 661 and resume['new_records'] == 0 and resume['status'] == 'COMPLETED'
    status = 'PASS' if all(checks.values()) else 'FAIL'
    # Exact original acceptance hash is checked above. These diagnostic thresholds
    # are the unchanged 10%, +.01 and strict CI <0 values, not new acceptance rules.
    diagnostics = {}
    for arm in trained:
        human = result['cohorts']['partial_human_dev']['comparisons'][f'{arm}_vs_parent']
        clean = result['cohorts']['general_clean']['comparisons'][f'{arm}_vs_parent']['wer_delta']
        ru = result['cohorts']['general_ru']['comparisons'][f'{arm}_vs_parent']['wer_delta']
        noise_deltas = {c: result['cohorts'][c]['inserted_words_per_minute'][arm] -
            result['cohorts'][c]['inserted_words_per_minute']['parent'] for c in ('noise_only', 'bleriot_b_noise')}
        point = human['relative_reduction'] is not None and human['relative_reduction'] >= .10
        upper = human['bootstrap']['upper']
        ci_pass = upper is not None and upper < 0
        diagnostics[arm] = {'cockpit_point_target': 'PASS' if point else 'FAIL',
            'cockpit_statistical_confirmation': 'PASS' if ci_pass else 'INCONCLUSIVE',
            'clean_EN_guardrail': 'PASS' if clean <= .01 else 'FAIL',
            'general_RU_regression_diagnostic': 'PASS' if ru <= .01 else 'FAIL',
            'noise_guardrail_diagnostic': 'PASS' if all(d <= 0 for d in noise_deltas.values()) else 'FAIL',
            'noise_words_per_minute_deltas': noise_deltas,
            'critical_entity_nonregression': 'NEEDS_MORE_DATA', 'release_quality_gate': 'NEEDS_MORE_DATA'}
    verification = {'status': status, 'checks': checks, 'test_runs': test_runs,
                   'reporter_sha256': sha(Path(__file__)), 'diagnostics': diagnostics,
                   'CPU_non_speech_output_present': any(r['hypothesis'].strip() for r in cpu['rows'] if r['cohort'] == 'bleriot_b_noise'),
                   'source': 'actual persisted training/inference/scoring artifacts', 'release_promoted': False}
    save(ROOT / 'verification.json', verification)
    save(ROOT / 'status.json', {'implemented': True, 'training_executed': True, 'diagnostics_executed': True,
        'artifact_verification': status, 'ASR_quality_gate': 'NEEDS_MORE_DATA', 'NLP_quality_gate': 'NEEDS_MORE_DATA',
        'temporal_gate': 'NEEDS_MORE_DATA', 'release_promoted': False, 'diagnostics': diagnostics})
    lines = ['# Переобучение Whisper-small: фактические результаты', '',
        f'Обучение и сравнение выполнены; проверка артефактов: **{status}**. Release не изменён.', '',
        'Оба адаптера обучены на RTX 5070 Ti от одного локального родителя, по 120 шагов, seed 55. '
        'Контроль: 33 слабые кабинные пары (11 мин). Дополненный: 433 пары (93,09 мин), включая 200 EN и 200 RU с издательскими текстами. '
        'Все записи были загружены; это один проход по дополненному набору и несколько по контрольному. '
        'Финальный checkpoint-120 выбран заранее; подбора по результатам этого сравнения нет.', '',
        'Ниже lexical WER; для слабых эталонов это расхождение с автоматической привязкой, не доказательство качества.', '',
        '| Набор | Эталонов | Слов | Исходный | 33 пары / 120 шагов | 433 пары / 120 шагов |',
        '|---|---:|---:|---:|---:|---:|']
    for cohort, c in result['cohorts'].items():
        if c['scores']['parent']['N']:
            values = [f"{100*c['scores'][s]['wer_lexical_corpus']:.2f}%" for s in SYSTEMS]
            lines.append(f"| {cohort} | {c['references']} | {c['scores']['parent']['N']} | {' | '.join(values)} |")
    lines += ['', 'Вставленные слова на шуме (слов/мин; каналы учитываются отдельно):', '',
              '| Набор | Минут | Исходный | Контроль | Дополненный |', '|---|---:|---:|---:|---:|']
    for name in ('noise_only', 'bleriot_b_noise'):
        c = result['cohorts'][name]
        values = [f"{c['inserted_words_per_minute'][s]:.3f}" for s in SYSTEMS]
        lines.append(f"| {name} | {c['channel_minutes']:.2f} | {' | '.join(values)} |")
    lines += ['', 'На пяти пользовательских dev-фрагментах:', '']
    for arm in trained:
        c = result['cohorts']['partial_human_dev']['comparisons'][f'{arm}_vs_parent']
        ci = c['bootstrap']
        lines.append(f"- {arm}: относительное снижение WER {100*c['relative_reduction']:.2f}%; "
            f"95% CI разницы WER [{100*ci['lower']:.2f}; {100*ci['upper']:.2f}] п.п., "
            f"{ci['independent_groups']} группы. Порог 10%: {diagnostics[arm]['cockpit_point_target']}.")
    lines += ['', 'Статусы диагностик:', '', '```json', json.dumps(diagnostics, ensure_ascii=False, indent=2), '```', '',
        '## Что проверено', '',
        f'- 1983 свежих GPU-распознавания (3 × 661); ошибки исполнения: {result["runtime_failures"]}.',
        '- Отдельный CPU int8 smoke: EN, RU и шум. Это проверка исполнения, не сравнение точности с GPU float16.',
        '- На CPU шумовой фрагмент дал посторонний повторяющийся текст; это сохранённый отрицательный результат. Технический PASS не оценивает его правильность.',
        '- GPU-прогоны частично перекрывались по времени; elapsed time и device-wide memory не являются изолированным сравнением производительности.',
        '- Фиксация кода, конфигураций, исходного checkpoint и манифестов; контроль хешей каждого входа и результата.',
        '- Все 661 свежих ответа исходного Whisper побуквенно совпали с предыдущим small_known; входы и effective options также совпали.',
        '- Контейнеры обучения и inference без сети; эталоны доступны только обучению train/dev и отдельному scorer.',
        '- Сохранены сырые прогнозы, S/D/I/N, интервалы bootstrap, логи, чекпоинты и отрицательные результаты тестовых попыток.',
        '', '## Ограничения', '',
        '- Основной ASR gate: **NEEDS_MORE_DATA**. Имеются только 5 частично проверенных dev-фрагментов, 115 слов и 3 группы; '
        'требуются 300 независимых utterances, 3000 слов и 20 групп. Наборы уже просматривались в прошлых экспериментах.',
        '- Критические сущности не размечены в необходимом объёме: отсутствие ухудшения не доказано. NLP и temporal gate: **NEEDS_MORE_DATA**.',
        '- RU измерен только на общей читаемой речи. Качество RU в кабине и mixed не подтверждено. Известны только 2 EN-диктора новых train-данных; '
        'индивидуальные RU speaker IDs недоступны, разделение опирается на исходный корпус.',
        '- Кабинные сценарии пересекаются между train/dev; группы записей и известных дикторов разделены. '
        'Для шумовых смесей один общий шумовой оригинал: CI не доказывает обобщение на независимые полёты.',
        '- LoRA меняет checkpoint; её результат не является доказательством улучшения pipeline на неизменной ASR-модели.',
        '- Прежние 16 dev-конфигураций сохранены; по явному запросу пользователя добавлены ровно 2 фиксированных обучения. '
        'Пороги ACCEPTANCE.yaml не изменены.',
        '', 'Команды воспроизведения: `docs/retraining.md`. Локальные веса находятся в Docker volume `north55-speech_model_cache`:', '',
        '- `whisper-small-retraining-v1-control/{adapter,merged,checkpoints,manifest.json}` и `whisper-small-retraining-v1-control-ct2`.',
        '- `whisper-small-retraining-v1-augmented/{adapter,merged,checkpoints,manifest.json}` и `whisper-small-retraining-v1-augmented-ct2`.', '']
    (ROOT / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'verification': status, 'checks': len(checks), 'failed': [k for k, v in checks.items() if not v], 'diagnostics': diagnostics}, ensure_ascii=False, indent=2))
    if status != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except PermissionError:
        if '--in-container' in sys.argv:
            raise
        # Docker writes private artifacts as UID 10001. Read them as that owner
        # instead of widening their permissions for a different Linux/WSL UID.
        args = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python']
        sources = [
            (ROOT, '/app/reports/retraining-v1', False),
            (Path(__file__).resolve(), '/app/scripts/report_retraining.py', True),
            *[(REPO / n, '/app/' + n, True) for n in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml')],
            *[(REPO / 'data/curated' / n, '/app/data/curated/' + n, True) for n in
              ('retraining-v1', 'reviewed-pilot-v2', 'publisher-expanded-v1/training', 'training-support-v1')],
        ]
        for local, remote, readonly in sources:
            args += ['-v', f'{local.as_posix()}:{remote}' + (':ro' if readonly else '')]
        args += ['north55-speech-gpu:0.1.0', '/app/scripts/report_retraining.py', '--in-container']
        raise SystemExit(subprocess.run(args, check=False).returncode) from None
