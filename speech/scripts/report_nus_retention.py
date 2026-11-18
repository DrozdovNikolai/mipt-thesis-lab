"""Read-only verification of completed retention evidence plus report presentation."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.core import file_hash
from north55_speech.metrics import corpus_counts
from north55_speech.retention import validate_retention_plan
from scripts.nus_convergence import read, save_new


def main(root, experiment):
    import torch

    plan, training = read(root / 'plan.json'), read(root / 'training.json')
    comparison, conversion = read(root / 'comparison.json'), read(root / 'conversion.json')
    inputs, counts = read(root / 'inputs.json'), read(root / 'scored-counts.json')
    validate_retention_plan(plan)
    for value in (training, comparison, conversion):
        if value['plan_sha256'] != file_hash(root / 'plan.json'):
            raise ValueError('Artifact belongs to another plan')
    for name, expected in read(root / 'frozen-files.json').items():
        if file_hash(root / 'frozen' / name) != expected:
            raise ValueError('Frozen file changed: ' + name)
    for name, expected in plan['scoring_sha256'].items():
        if file_hash(root / 'scoring' / name) != expected:
            raise ValueError('Historical scoring changed')
    if file_hash(root / 'protocol.md') != plan['protocol_sha256'] or file_hash(root / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Protocol or input changed')
    optimizer_audit = {}
    for arm in ('1', '2'):
        folder = experiment / 'training' / f'checkpoint-{arm}'
        for name, expected in training['checkpoints'][arm].items():
            if file_hash(folder / name) != expected:
                raise ValueError('Checkpoint changed')
        state = torch.load(folder / 'optimizer.pt', map_location='cpu', weights_only=True)
        optimizer_audit[arm] = {'sha256': file_hash(folder / 'optimizer.pt'),
            'actual_updates': sorted({int(v['step'].item()) for v in state['state'].values()}),
            'tensors': len(state['state']), 'learning_rates': [g['lr'] for g in state['param_groups']]}
        manifest = conversion['models'][arm]
        model_root = experiment / 'models' / manifest['model']
        if read(model_root / 'manifest.json') != manifest:
            raise ValueError('Model manifest changed')
        for name, expected in manifest['files'].items():
            if file_hash(model_root / name) != expected:
                raise ValueError('Converted model changed')
    executions = {p.parent.name: read(p) for p in root.glob('*/execution.json')}
    for name, execution in executions.items():
        if execution['plan_sha256'] != file_hash(root / 'plan.json'):
            raise ValueError('Inference plan mismatch')
        for filename, expected in execution['prediction_sha256'].items():
            if file_hash(root / name / 'predictions' / filename) != expected:
                raise ValueError('Saved prediction changed')
    for cohort, entry in comparison['cohorts'].items():
        group = inputs['fit'] if cohort == 'nus_training_fit' else [i for i in inputs['transfer'] if i['cohort'] == cohort]
        for system, expected in entry['scores'].items():
            if corpus_counts([counts[i['id']][system] for i in group]) != expected:
                raise ValueError('Aggregate does not reproduce individual counts')
    tests = {}
    for name in ('results', 'backcompat'):
        suites = list(ET.parse(root / 'tests' / (name + '.xml')).getroot().iter('testsuite'))
        tests[name] = {k: sum(int(s.attrib.get(k, 0)) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
    runtime = [read(p) for p in root.glob('north55-*.json')]
    inference = [r for r in runtime if r['command'][3:4] in (['fit'], ['transfer'], ['cpu'])]
    training_runtime = [r for r in runtime if r['command'][3:4] == ['train']]
    gpu_calls = sum(e['new_ASR_calls'] for e in executions.values() if e['actual_device'] == 'cuda')
    cpu_calls = sum(e['new_ASR_calls'] for e in executions.values() if e['actual_device'] == 'cpu')
    checks = {
        'two_1200_actual_optimizer_trajectories': all(a['actual_updates'] == [1200] and a['tensors'] == 96 for a in optimizer_audit.values()),
        'both_LR_2e_5': all(a['learning_rates'] == [2e-5] for a in optimizer_audit.values()),
        'identical_initial_adapters': len({a['initial_adapter_sha256'] for a in training['arms'].values()}) == 1,
        'identical_schedule': len({a['schedule_sha256'] for a in training['arms'].values()}) == 1,
        'same_675_train_pairs_4800_visits_each': all(set(a['coverage']) == set(plan['selected_ids']) and len(a['coverage']) == 675
            and sum(a['coverage'].values()) == 4800 for a in training['arms'].values()),
        'training_language_prefixes': len(training['audio_label_contract']) == 675 and all(r['prefix'] ==
            [50258, {'en': 50259, 'ru': 50263}[r['language']], 50359, 50363] for r in training['audio_label_contract']),
        'no_truncation': all(0 < r['samples'] <= 480000 and r['tokens'] <= 448 for r in training['audio_label_contract']),
        'frozen_base_encoder': all(a['encoder_unchanged'] and a['frozen_base_unchanged'] for a in training['arms'].values()),
        'teacher_probe_immutable': all(a['teacher_before_sha256'] == a['teacher_after_sha256'] for a in training['arms'].values()),
        'teacher_probe_same_between_arms': len({a['teacher_before_sha256'] for a in training['arms'].values()}) == 1,
        'merged_encoders_unchanged': set(conversion['models']) == {'1', '2'} and all(m['encoder_unchanged'] for m in conversion['models'].values()),
        '51_tests_passed': tests['results']['tests'] == 11 and tests['backcompat']['tests'] == 40 and
            all(not t[k] for t in tests.values() for k in ('failures', 'errors', 'skipped')),
        'all_six_ASR_stages': set(executions) == {f'{stage}-{arm}' for stage in ('fit', 'transfer', 'cpu-fit') for arm in (1, 2)},
        'exact_ASR_budget': gpu_calls == 868 and cpu_calls == 4,
        'zero_ASR_runtime_failures': all(not e['runtime_failures'] for e in executions.values()),
        'GPU_float16': all(e['actual_precision'] == 'float16' for e in executions.values() if e['actual_device'] == 'cuda'),
        'both_CPU_languages': all(executions[f'cpu-fit-{arm}']['records'] == 2 and executions[f'cpu-fit-{arm}']['actual_device'] == 'cpu'
            and {read(p)['input_language'] for p in (root / f'cpu-fit-{arm}' / 'predictions').glob('*.json')} == {'en', 'ru'} for arm in (1, 2)),
        'offline': all(r['network'] == 'none' for r in runtime),
        'train_has_no_scoring': len(training_runtime) == 1 and all(not any(m['Destination'] == '/study' or '/scoring' in m['Destination'] for m in r['mounts']) for r in training_runtime),
        'inference_has_no_references': len(inference) >= 6 and all(not any(m['Destination'] in ('/study', '/train/subset.jsonl') or '/scoring' in m['Destination'] for m in r['mounts']) for r in inference),
        'source_volumes_readonly': all(not m['RW'] for r in runtime for m in r['mounts'] if m['Destination'] in ('/models', '/audio')),
        'Linux_replay': read(root / 'cross-platform-replay.json')['status'] == 'PASS',
        'tampered_prediction_rejected': read(root / 'integrity-rejection.json')['status'] == 'PASS',
        'fixed_candidate_no_promotion': comparison['fixed_candidate'] == 2 and comparison['release_promoted'] is False,
    }
    summary = {'implemented': True, 'executed': True, 'artifact_verification': 'PASS' if all(checks.values()) else 'FAIL',
        'checks': checks, 'release': comparison['release'], 'independent_quality': 'NEEDS_MORE_DATA',
        'test_accessed': False, 'release_promoted': False, 'tests': tests, 'optimizer_audit': optimizer_audit,
        'new_GPU_ASR_calls': gpu_calls, 'new_CPU_ASR_calls': cpu_calls,
        'training_seconds': {k: v['training_seconds'] for k, v in training['arms'].items()},
        'comparison_sha256': file_hash(root / 'comparison.json'), 'plan_sha256': file_hash(root / 'plan.json'),
        'training_sha256': file_hash(root / 'training.json'), 'report_script_sha256': file_hash(Path(__file__))}
    save_new(root / 'summary.json', summary)
    lines = ['# NUS: обычное обучение против удержания исходной модели', '',
        f"Реализовано и выполнено. Артефакты/исполнение: **{summary['artifact_verification']}**. "
        f"Фиксированный candidate arm 2: **{summary['release']}**. Независимая оценка: **NEEDS_MORE_DATA**.", '',
        'Оба свежих адаптера Whisper-small обучены на одинаковых 675 прежних train-парах: '
        '275 NUS + 200 LibriSpeech EN + 200 FLEURS RU. Всего 94.35 минуты. '
        'Нет новых текстов, псевдо-gold, ручной переразметки или изменения splits. '
        'NUS остаётся одной train-группой с неизвестными говорящими и слабым статусом эталонов.', '',
        'Arm 1 — CE; arm 2 — CE + KL(teacher || student), вес 1, температура 2 и множитель T². '
        'Teacher — исходный base с отключённым адаптером и dropout. Штраф по всем допустимым '
        'позициям train-токенов; teacher не заменяет тексты и не видит контрольные ответы. '
        'Мотивация: [Learning without Forgetting](https://arxiv.org/abs/1606.09282). '
        'Её применимость к этому материалу проверяется измерениями ниже.', '',
        'По 1200 фактических обновлений AdamW, по 4800 предъявлений, все 675 пар в каждом arm. '
        'Идентичные начальные адаптеры и порядок примеров; constant LR 2e-5, rank 8, alpha 16, '
        'dropout .05, seed 55, batch 1 / accumulation 4. Только 96 decoder LoRA-тензоров '
        '(589824 параметра). BF16 autocast, FP32 weights/AdamW/KL, TF32 off, без GradScaler. '
        'Энкодер и все base-тензоры сохранены побайтно; teacher probe до/после совпадает. '
        'Никакого выбора промежуточного checkpoint. Оба arm имеют общую новую точность '
        'обучения и schedule: причинное сравнение KL выполняется между ними, а не со старым FP16 опытом.', '',
        '## Lexical WER', '', '| Материал | Клипы / группы | Исходный | CE, arm 1 | CE+KL, arm 2 |',
        '|---|---:|---:|---:|---:|']
    for cohort, entry in comparison['cohorts'].items():
        if entry['scores']['parent']['wer_lexical_corpus'] is None:
            continue
        values = [entry['scores'][a]['wer_lexical_corpus']*100 for a in ('parent', '1', '2')]
        lines.append(f"| {cohort} | {entry['samples']} / {entry['groups']} | " + ' | '.join(f'{v:.4f}%' for v in values) + ' |')
    lines += ['', 'NUS-fit — ошибка на обучающих аудио, не доказательство переноса.', '',
        '## Ложные слова на неречевом аудио', '', '| Материал | Минуты | Исходный | CE | CE+KL |', '|---|---:|---:|---:|---:|']
    for cohort in ('noise_only', 'bleriot_b_noise'):
        entry = comparison['cohorts'][cohort]
        lines.append(f"| {cohort} | {entry['minutes']:.3f} | " + ' | '.join(f"{entry['inserted_words_per_minute'][a]:.4f}" for a in ('parent', '1', '2')) + ' |')
    human = comparison['cohorts']['partial_human_dev']['comparisons']
    lines += ['', '## Описательная неопределённость', '']
    for key, label in [('2_vs_parent', 'CE+KL минус исходный'), ('2_vs_1', 'CE+KL минус CE')]:
        interval = human[key]['bootstrap']
        lines += [f"{label}, 95% paired cluster-bootstrap CI WER: {interval['lower']*100:+.2f}…{interval['upper']*100:+.2f} п.п. "
            '2000 resamples, seed 55; только 5 человеческих dev-фрагментов, 115 слов, 3 ранее просмотренные группы.', '']
    lines += ['Это не независимая статистическая приёмка. RU имеет одну консервативную группу, '
        'и вырожденный bootstrap не оценивает популяционную неопределённость.', '',
        f"Проверки candidate: `{json.dumps(comparison['checks']['2'])}`.", '',
        '## Исполнение и границы', '',
        '51 тест, 868 GPU ASR и 4 CPU smoke EN/RU; нулевые runtime failures проверяются в summary. '
        'CUDA inference float16, одинаковые beam/temperature/language/decoding options и PCM. '
        'Исторические ответы без runtime PCM имеют отдельную явную реконструкцию из сохранённого '
        'файла; она не выдаётся за исторически записанный checksum. PowerShell/Linux replay '
        'пересчитывает сохранённые ответы, не повторяет обучение. Время обучения: '
        + ', '.join(f"arm {k}: {v:.2f} с" for k, v in summary['training_seconds'].items()) + '.', '',
        'Исполненная проверка отказа: изменённая гипотеза в отдельной копии отвергнута '
        'scorer по hash mismatch до расчёта метрик; оригинальный ответ сохранён. '
        'Audit: integrity-rejection.json, дополнительных ASR-вызовов нет.', '',
        'Не хватает независимых 300 кабинных фрагментов, 3000 слов, 20 групп и 100 проверенных '
        'критических сущностей. Event/NLP и temporal labels не появились. Общий RU control '
        'не подтверждает RU/mixed cockpit. Пороги ACCEPTANCE и прежний исчерпанный release-search '
        'не менялись; отдельный diagnostic не расширяет разрешение на release. '
        'Сравнение адаптированных весов не является доказательством улучшения preprocessing '
        'на одном checkpoint. В рабочем сервисе остаётся прежняя модель.', '',
        '[Протокол](protocol.md) · [Метрики](comparison.json) · [Проверки](summary.json) · '
        '[Команды и ограничения воспроизведения](../../docs/nus_retention.md)', '']
    if (root / 'report.md').exists():
        raise ValueError('Preserve existing report')
    (root / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({k: summary[k] for k in ('artifact_verification', 'release', 'new_GPU_ASR_calls', 'new_CPU_ASR_calls')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/report'))
    parser.add_argument('--experiment', type=Path, default=Path('/experiment'))
    args = parser.parse_args()
    main(args.root, args.experiment)
