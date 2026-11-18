"""Read the completed continuation study; verify artifacts and write a scoped report."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.core import file_hash
from north55_speech.metrics import corpus_counts, edit_counts
from scripts.nus_convergence import read, save_new


def main(root):
    plan = read(root / 'plan.json')
    comparison = read(root / 'comparison.json')
    training, conversion = read(root / 'training.json'), read(root / 'conversion.json')
    frozen = read(root / 'frozen-files.json')
    if any(v['plan_sha256'] != file_hash(root / 'plan.json') for v in (comparison, training, conversion)):
        raise ValueError('Artifact plan identity differs')
    for name, expected in frozen.items():
        if file_hash(root / 'frozen' / name) != expected:
            raise ValueError('Frozen code changed: ' + name)
    for name, expected in plan['scoring_sha256'].items():
        if file_hash(root / 'scoring' / name) != expected:
            raise ValueError('Frozen references/baseline changed: ' + name)
    if file_hash(root / 'inputs.json') != plan['inputs_sha256'] or file_hash(root / 'protocol.md') != plan['protocol_sha256']:
        raise ValueError('Frozen population/protocol changed')
    inputs, refs = read(root / 'inputs.json'), read(root / 'scoring/references.json')
    parent = read(root / 'scoring/parent.json')
    counts = {}
    for item in inputs['transfer']:
        ref = refs[item['reference_id']]
        values = {'parent': edit_counts(ref, parent[item['id']]['hypothesis'])}
        for label, step in (('source240', 0), ('final640', 400)):
            prediction = read(root / f'transfer-{step}/predictions' / (item['id'] + '.json'))
            values[label] = edit_counts(ref, prediction['hypothesis'] if prediction['runtime_failure'] is None else '')
        counts[item['id']] = {'cohort': item['cohort'], 'group_id': item['group_id'], 'scores': values}
    for cohort in {i['cohort'] for i in inputs['transfer']}:
        group = [c for c in counts.values() if c['cohort'] == cohort]
        for system in ('parent', 'source240', 'final640'):
            if corpus_counts([c['scores'][system] for c in group]) != comparison['transfer'][cohort]['scores'][system]:
                raise ValueError('Per-record counts differ from the frozen scorer aggregate')
    save_new(root / 'scored-counts.json', {'plan_sha256': file_hash(root / 'plan.json'), 'transfer': counts})
    executions = {p.parent.name: read(p) for p in root.glob('*/execution.json')}
    for name, execution in executions.items():
        if execution['plan_sha256'] != file_hash(root / 'plan.json'):
            raise ValueError('Inference plan mismatch')
        for filename, expected in execution['prediction_sha256'].items():
            if file_hash(root / name / 'predictions' / filename) != expected:
                raise ValueError('Prediction changed: ' + filename)
    suites = list(ET.parse(root / 'tests/results.xml').getroot().iter('testsuite'))
    tests = {k: sum(int(s.attrib.get(k, 0)) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
    compatibility_suites = list(ET.parse(root / 'tests/backcompat.xml').getroot().iter('testsuite'))
    compatibility = {k: sum(int(s.attrib.get(k, 0)) for s in compatibility_suites) for k in ('tests', 'failures', 'errors', 'skipped')}
    runtime = [read(p) for p in root.glob('north55-*.json')]
    inference = [r for r in runtime if r['command'][3:4] in (['fit'], ['transfer'], ['cpu'])]
    optimizer = training['optimizer_continuation']
    gpu_calls = sum(r['new_ASR_calls'] for r in executions.values() if r['actual_device'] == 'cuda')
    cpu_calls = sum(r['new_ASR_calls'] for r in executions.values() if r['actual_device'] == 'cpu')
    checks = {
        'fixed_400_added_steps': training['global_steps'] == 400,
        'per_record_edit_counts_match': True,
        'optimizer_restored_240_to_640': optimizer['source_steps'] == optimizer['restored_steps'] == [240.] and optimizer['final_steps'] == [640.],
        'optimizer_all_states_restored': optimizer['source_state_count'] == 144,
        'AMP_scaler_restored': optimizer['scaler_restored'],
        'constant_LR_2e5': training['arguments']['learning_rate'] == 2e-5 and training['arguments']['lr_scheduler_type'] == 'constant',
        'same_32_train_originals': set(training['coverage']) == set(plan['selected_ids']) and sum(training['coverage'].values()) == 1600,
        'all_milestones_saved_and_converted': set(training['checkpoints']) == {'160', '400'} and set(conversion['models']) == {'0', '160', '400'},
        'eight_tests_passed': tests['tests'] == 8 and not any(tests[k] for k in ('failures', 'errors', 'skipped')),
        'eight_backward_compatibility_tests_passed': compatibility['tests'] == 8 and not any(compatibility[k] for k in ('failures', 'errors', 'skipped')),
        'both_transfer_endpoints_executed': all(executions.get('transfer-' + str(s), {}).get('records') == 402 for s in (0, 400)),
        'only_prespecified_inference': set(executions) == {'fit-160', 'fit-400', 'transfer-0', 'transfer-400', 'cpu-fit-400'},
        'exact_ASR_budget': gpu_calls == 868 and cpu_calls == 1,
        'inference_recorded_offline': len(inference) >= 5 and all(r['network'] == 'none' for r in inference),
        'references_absent_from_generation': bool(inference) and all(not any(m['Destination'] in ('/study', '/train/subset.jsonl') or '/scoring' in m['Destination'] for m in r['mounts']) for r in inference),
        'original_volumes_readonly': all(not m['RW'] for r in runtime for m in r['mounts'] if m['Destination'] in ('/models', '/audio', '/source_experiment')),
        'all_ASR_calls_succeeded': all(not r['runtime_failures'] for r in executions.values()),
        'GPU_float16': all(r['actual_precision'] == 'float16' for r in executions.values() if r['actual_device'] == 'cuda'),
        'CPU_smoke': executions.get('cpu-fit-400', {}).get('actual_device') == 'cpu',
        'linux_replay': (root / 'cross-platform-replay.json').is_file() and read(root / 'cross-platform-replay.json')['status'] == 'PASS',
        'no_release_promotion': comparison['release_promoted'] is False,
    }
    summary = {'implemented': True, 'executed': True,
        'artifact_verification': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
        'fit_diagnostic': comparison['fit_diagnostic'], 'release': comparison['release'],
        'independent_quality': 'NEEDS_MORE_DATA', 'release_promoted': False, 'test_accessed': False,
        'additional_training_steps': 400, 'total_optimizer_steps': optimizer['final_steps'],
        'new_GPU_ASR_calls': gpu_calls, 'new_CPU_ASR_calls': cpu_calls, 'tests': tests, 'backward_compatibility_tests': compatibility,
        'fit_curve': comparison['fit_curve'], 'transfer': comparison['transfer'],
        'quality_checks': comparison['checks'], 'plan_sha256': file_hash(root / 'plan.json'),
        'training_sha256': file_hash(root / 'training.json'), 'comparison_sha256': file_hash(root / 'comparison.json'),
        'report_script_sha256': file_hash(Path(__file__))}
    save_new(root / 'summary.json', summary)
    lines = ['# NUS: продолжение обучения и проверка других записей', '',
        f"Протокол реализован и выполнен. Проверка артефактов: **{summary['artifact_verification']}**. "
        f"Release: **{summary['release']}**. Независимая оценка: **NEEDS_MORE_DATA**.", '',
        '## Обучение и assumptions', '',
        'Одна заранее зафиксированная траектория: исходный adapter step 240 → ещё 400 шагов '
        'с constant LR 2e-5. Восстановлены 144 состояния AdamW, моменты, счётчики и AMP scaler. '
        'Итоговый счётчик каждого состояния — 640. Новый порядок данных/dropout seeded 55; '
        'это отдельная фаза, не продолжение прежнего расписания с нулевым LR.', '',
        'Те же 32 готовые NUS-пары, 2.045 минуты, 145 слов; тексты не исправлялись. '
        'Готовые расшифровки источника допускаются для обучения, но не прошли полную локальную '
        'человеческую сверку и не являются gold для приёмки. '
        '400 дополнительных шагов = 1600 позиций загрузчика, 50 проходов каждой пары. '
        'Все данные остаются в одной исходной train-группе; личности говорящих неизвестны.', '',
        '| Модель / всего шагов | WER своих 32 примеров | S | D | I |', '|---|---:|---:|---:|---:|']
    for step, value in comparison['fit_curve'].items():
        lines.append(f"| {step} | {value['wer_lexical_corpus']*100:.2f}% | {value['S']} | {value['D']} | {value['I']} |")
    lines += ['', f"Диагностический train WER ≤10%: **{comparison['fit_diagnostic']}**. "
        'Этот критерий не является приёмкой. Измерен самостоятельный вывод сохранённых CT2 '
        'float16-весов; teacher-forced loss не используется вместо WER.', '',
        'В comparison.json сохранён вторичный canonical WER с существующим симметричным '
        'нормализатором. Основные числа и решение используют неизменный lexical_normalizer_v1.', '',
        '## Те же 402 других входа', '',
        'Исходный step 240 и заранее выбранный final step 640 проверены независимо от train WER. '
        'Промежуточный total step 400 здесь не проверялся и не выбирался. Parent — прежний '
        'неадаптированный Whisper-small; та же точность float16, тот же waveform и decoder.', '',
        '| Набор | Клипов / групп | Parent WER | Step 240 WER | Step 640 WER |', '|---|---:|---:|---:|---:|']
    for cohort, value in comparison['transfer'].items():
        if cohort in ('noise_only', 'bleriot_b_noise'):
            continue
        values = [f"{value['scores'][s]['wer_lexical_corpus']*100:.2f}%" for s in ('parent', 'source240', 'final640')]
        lines.append(f"| {cohort} | {value['samples']} / {value['groups']} | " + ' | '.join(values) + ' |')
    lines += ['', '52 из 243 других NUS-клипов повторяют нормализованный текст обучающих пар; '
        'эти строки показаны отдельно от 191 клипа с другим текстом и являются подмножествами '
        'nus_same_source_nonfit. Это диагностика внутри ранее использованной общей train-группы. '
        'Она не доказывает перенос на новых говорящих, сессии или спонтанную кабинную речь.', '',
        '| Неречевой контроль | Минут | Parent вставок/мин | Step 240 | Step 640 |', '|---|---:|---:|---:|---:|']
    for cohort in ('noise_only', 'bleriot_b_noise'):
        value = comparison['transfer'][cohort]
        scores = value['inserted_words_per_minute']
        lines.append(f"| {cohort} | {value['minutes']:.3f} | {scores['parent']:.3f} | {scores['source240']:.3f} | {scores['final640']:.3f} |")
    lines += ['', f"Доступные проверки против parent: `{json.dumps(comparison['checks'])}`.", '',
        'Bootstrap 2000, seed 55, 95% CI сохранён для доступных человеческих/general dev-контролей '
        'для final–parent и final–source. Эти повторно изученные наборы не становятся новым final test. '
        'Для RU с одной консервативной группой численно вырожденный bootstrap-интервал '
        'не является надёжной оценкой неопределённости. '
        'Для всего NUS с одной исходной группой статистическое подтверждение не заявляется.', '',
        '## Проверки и ограничения', '',
        f"Выполнены {gpu_calls} новых GPU ASR-вызовов, {cpu_calls} CPU smoke и 16 тестов (8 новых + 8 совместимости). "
        'Inference не получает эталоны; сеть выключена. Прежние модели и аудио только для чтения. '
        'Контроль входов сверяет hashes, effective decoder options и PCM. Для старых ответов '
        'без записанного runtime PCM реконструкция из исходного файла явно отмечена в '
        'legacy-waveform-evidence.json и не выдаётся за исторически записанный checksum.', '',
        'PowerShell/Linux пересчёт и повторное использование ответов отражены в cross-platform-replay.json. '
        'Параллельные GPU ASR-процессы не используются для заявления о производительности.', '',
        'Независимого test на ≥300 фрагментах / ≥3000 словах / ≥20 группах нет. '
        'Пять человеческих кабинных dev-фрагментов содержат 115 слов и три группы. '
        'Нет необходимых независимых человеческих сущностей, event labels и temporal-интервалов; '
        'NLP/temporal и качество RU/mixed cockpit этот опыт не подтверждает. '
        'Условия ACCEPTANCE и прежний исчерпанный dev-search не менялись. '
        'Это отдельный диагностический LoRA-опыт, а не сравнение pipeline-этапов на одном checkpoint. '
        'Ни одна новая версия не подключена к serving.', '',
        '[Протокол](protocol.md) · [Все измерения](comparison.json) · [Проверки](summary.json) · '
        '[Вывод и следующий шаг](decision.md) · '
        '[Команды](../../docs/nus_continuation.md)', '']
    if (root / 'report.md').exists():
        raise ValueError('Preserve existing report')
    (root / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({k: summary[k] for k in ('artifact_verification', 'fit_diagnostic', 'release', 'new_GPU_ASR_calls', 'new_CPU_ASR_calls')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/report'))
    main(parser.parse_args().root)
