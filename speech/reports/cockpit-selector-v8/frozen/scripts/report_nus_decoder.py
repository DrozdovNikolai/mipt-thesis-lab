"""Verify completed decoder-only artifacts and present the measured result."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.core import file_hash
from north55_speech.metrics import corpus_counts
from scripts.nus_convergence import read, save_new


def main(root):
    plan, training = read(root / 'plan.json'), read(root / 'training.json')
    comparison, conversion = read(root / 'comparison.json'), read(root / 'conversion.json')
    inputs, counts = read(root / 'inputs.json'), read(root / 'scored-counts.json')
    optimizer_audit = read(root / 'optimizer-audit.json')
    if optimizer_audit['decoder240']['optimizer_sha256'] != training['checkpoints']['240']['optimizer.pt']:
        raise ValueError('Optimizer audit is not from the saved checkpoint')
    for value in (training, comparison, conversion):
        if value['plan_sha256'] != file_hash(root / 'plan.json'):
            raise ValueError('Artifact identity differs')
    for name, expected in read(root / 'frozen-files.json').items():
        if file_hash(root / 'frozen' / name) != expected:
            raise ValueError('Frozen implementation changed')
    for name, expected in plan['scoring_sha256'].items():
        if file_hash(root / 'scoring' / name) != expected:
            raise ValueError('Frozen references/baselines changed')
    if file_hash(root / 'protocol.md') != plan['protocol_sha256'] or file_hash(root / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Protocol/input population changed')
    executions = {p.parent.name: read(p) for p in root.glob('*/execution.json')}
    for name, execution in executions.items():
        if execution['plan_sha256'] != file_hash(root / 'plan.json'):
            raise ValueError('Inference plan mismatch')
        for filename, expected in execution['prediction_sha256'].items():
            if file_hash(root / name / 'predictions' / filename) != expected:
                raise ValueError('Stored answer changed')
    for step, result in comparison['checkpoints'].items():
        for cohort, entry in result['cohorts'].items():
            group = [i for i in inputs['fit'] + inputs['transfer'] if i['cohort'] == cohort]
            for system, expected in entry['scores'].items():
                if corpus_counts([counts[step][i['id']][system] for i in group]) != expected:
                    raise ValueError('Per-record counts differ from aggregate')
    tests = {}
    for name in ('results', 'backcompat'):
        suites = list(ET.parse(root / 'tests' / (name + '.xml')).getroot().iter('testsuite'))
        tests[name] = {k: sum(int(s.attrib.get(k, 0)) for s in suites) for k in ('tests', 'failures', 'errors', 'skipped')}
    runtime = [read(p) for p in root.glob('north55-*.json')]
    inference = [r for r in runtime if r['command'][3:4] in (['fit'], ['transfer'], ['cpu'])]
    gpu_calls = sum(r['new_ASR_calls'] for r in executions.values() if r['actual_device'] == 'cuda')
    cpu_calls = sum(r['new_ASR_calls'] for r in executions.values() if r['actual_device'] == 'cpu')
    required = {f'{s}-{n}' for s in ('fit', 'transfer', 'cpu-fit') for n in (240, 1200)}
    checks = {
        'fixed_1200_steps': training['global_steps'] == 1200,
        'actual_optimizer_updates': all(training['milestones'][s]['optimizer_steps'] == [float(s)] for s in ('240', '1200')),
        'full_675_train_pairs': set(training['coverage']) == set(plan['selected_ids']) and len(training['coverage']) == 675,
        'language_prefixes_match_annotations': len(training['audio_label_contract']) == 675 and all(r['prefix'] == [50258, {'en': 50259, 'ru': 50263}[r['language']], 50359, 50363] for r in training['audio_label_contract']),
        'no_training_truncation': all(r['samples'] <= 480000 and r['label_length'] <= 448 for r in training['audio_label_contract']),
        'encoder_identical': training['encoder_before'] == training['encoder_after'],
        'both_milestones_encoder_identical': all(v['encoder_unchanged'] for v in training['milestones'].values()),
        '48_decoder_modules_96_tensors': len(training['target_modules']) == 48 and len(training['trainable_tensors']) == 96,
        '589824_trainable_parameters': training['parameters']['trainable'] == 589824,
        'both_merged_encoders_identical': set(conversion['models']) == {'240', '1200'} and all(m['encoder_unchanged'] for m in conversion['models'].values()),
        '40_tests_passed': tests['results']['tests'] == 8 and tests['backcompat']['tests'] == 32 and all(not t[k] for t in tests.values() for k in ('failures', 'errors', 'skipped')),
        'all_stages_recorded': set(executions) == required,
        'exact_ASR_budget': gpu_calls == 868 and cpu_calls == 4,
        'zero_ASR_runtime_failures': all(not e['runtime_failures'] for e in executions.values()),
        'GPU_float16': all(e['actual_precision'] == 'float16' for e in executions.values() if e['actual_device'] == 'cuda'),
        'two_CPU_languages_each_checkpoint': all(executions[f'cpu-fit-{s}']['records'] == 2 and executions[f'cpu-fit-{s}']['actual_device'] == 'cpu' for s in (240, 1200)),
        'offline_inference': len(inference) >= 6 and all(r['network'] == 'none' for r in inference),
        'references_absent_from_inference': bool(inference) and all(not any(m['Destination'] in ('/study', '/train/subset.jsonl') or '/scoring' in m['Destination'] for m in r['mounts']) for r in inference),
        'old_models_audio_readonly': all(not m['RW'] for r in runtime for m in r['mounts'] if m['Destination'] in ('/models', '/audio')),
        'Linux_replay': read(root / 'cross-platform-replay.json')['status'] == 'PASS',
        'no_promotion': comparison['release_promoted'] is False,
    }
    summary = {'implemented': True, 'executed': True, 'artifact_verification': 'PASS' if all(checks.values()) else 'FAIL',
        'artifact_integrity': 'PASS' if all(v for k, v in checks.items() if k != 'actual_optimizer_updates') else 'FAIL',
        'checks': checks, 'release': comparison['release'], 'independent_quality': 'NEEDS_MORE_DATA',
        'test_accessed': False, 'release_promoted': False, 'tests': tests,
        'new_GPU_ASR_calls': gpu_calls, 'new_CPU_ASR_calls': cpu_calls, 'training_loop_steps': training['global_steps'],
        'actual_optimizer_updates': {s: v['optimizer_steps'] for s, v in training['milestones'].items()},
        'historical_optimizer_audit': optimizer_audit,
        'protocol_execution': 'PASS' if checks['actual_optimizer_updates'] else 'FAIL',
        'training_rows': 675, 'train_visits': sum(training['coverage'].values()),
        'comparison_sha256': file_hash(root / 'comparison.json'), 'plan_sha256': file_hash(root / 'plan.json'),
        'training_sha256': file_hash(root / 'training.json'), 'report_script_sha256': file_hash(Path(__file__))}
    save_new(root / 'summary.json', summary)
    lines = ['# NUS: новый адаптер только для декодера', '',
        f"Реализовано и выполнено. Целостность артефактов: **{summary['artifact_integrity']}**. "
        f"Точное исполнение frozen-протокола: **{summary['protocol_execution']}**. "
        f"Итоговый candidate: **{summary['release']}**. Независимая оценка: **NEEDS_MORE_DATA**.", '',
        'Одна траектория с исходного Whisper-small: 675 прежних пар (275 NUS, 200 EN, 200 RU), '
        '94.35 минуты. Нет новых расшифровок, исправления текстов и пересмотра splits. '
        'NUS — одна общая train-группа с неизвестными говорящими и без локальной полной '
        'человеческой сверки текста. Готовые тексты пригодны для обучения, но не заменяют gold.', '',
        'Обучались только 589824 параметра LoRA в 48 decoder q/v projections, 96 тензоров. '
        'Веса encoder побайтно проверены до/после обучения, в checkpoints и после merge. '
        'Это новый decoder-only train с самого начала, а не отключение части совместно обученного адаптера.', '',
        f"Выполнены 1200 шагов цикла и {summary['train_visits']} позиций загрузчика; контрольные точки 240 и 1200. "
        f"Фактические счётчики AdamW: {summary['actual_optimizer_updates']}. "
        'Первые 240 шагов — прежний спад LR 5e-5; следующие 960 — constant 2e-5. '
        'Моменты AdamW сохранялись. Seed 55, rank 8, alpha 16, dropout .05, batch 1/accumulation 4, '
        'FP16/TF32 off. Итоговая точка 1200 задана до обучения, dev early stopping отсутствует.', '',
        'Если AdamW-счётчик меньше номера шага цикла, FP16 scaler пропустил обновление. '
        'Такой пропуск не подменяется выполненным шагом и не компенсируется дополнительным '
        'обучением после исчерпания frozen-бюджета; нарушение точного числа updates отражено '
        'в protocol_execution и artifact_verification. Метрики сохранённых весов всё равно измеряются.', '',
        'Дополнительно проверен сохранённый optimizer прежнего joint240: у него тоже '
        '239 фактических AdamW updates при 240 шагах Trainer. Его hash соответствует прежнему '
        'training.json; старые веса и ответы не менялись. Обе ранние точки сравниваются '
        'с одинаковым фактическим числом обновлений (optimizer-audit.json).', '',
        '## Измерения', '',
        'Меньший lexical WER лучше. Обе точки проверены на тех же входах; parent — исходный '
        'Whisper-small, joint240 — прежний совместно обученный NUS-адаптер. Все ASR-сравнения '
        'используют CT2 float16 и прежний decoder с timestamps, без подсказок/VAD/denoise/redecode.', '',
        '| Набор | Клипов / групп | Parent | Joint240 | Decoder240 | Decoder1200 |',
        '|---|---:|---:|---:|---:|---:|']
    first, last = (comparison['checkpoints'][s]['cohorts'] for s in ('240', '1200'))
    for cohort, entry in last.items():
        if cohort in ('noise_only', 'bleriot_b_noise'):
            continue
        rates = [entry['scores'][s]['wer_lexical_corpus'] for s in ('parent', 'joint240')]
        rates += [first[cohort]['scores']['candidate']['wer_lexical_corpus'], entry['scores']['candidate']['wer_lexical_corpus']]
        lines.append(f"| {cohort} | {entry['samples']} / {entry['groups']} | " + ' | '.join(f'{v*100:.2f}%' for v in rates) + ' |')
    lines += ['', 'Строка nus_training_fit — все 275 обучающих NUS-клипов. Выигрыш здесь не '
        'доказывает перенос на другие фразы, говорящих и сессии. Остальные наборы — ранее '
        'использованные dev/controls; они не становятся новым независимым test.', '',
        '| Неречевой контроль | Минут | Parent вставок/мин | Joint240 | Decoder240 | Decoder1200 |', '|---|---:|---:|---:|---:|---:|']
    for cohort in ('noise_only', 'bleriot_b_noise'):
        e = last[cohort]
        rates = [e['inserted_words_per_minute'][s] for s in ('parent', 'joint240')]
        rates += [first[cohort]['inserted_words_per_minute']['candidate'], e['inserted_words_per_minute']['candidate']]
        lines.append(f"| {cohort} | {e['minutes']:.3f} | " + ' | '.join(f'{v:.3f}' for v in rates) + ' |')
    for step, result in comparison['checkpoints'].items():
        lines += ['', f"Проверки step {step}: `{json.dumps(result['checks'])}`."]
    human = last['partial_human_dev']['comparisons']['candidate_vs_parent']['bootstrap']
    lines += ['', f"95% paired cluster-bootstrap CI изменения cockpit dev WER (final–parent): "
        f"{human['lower']*100:+.2f}…{human['upper']*100:+.2f} п.п., 2000 повторов, seed 55. "
        'Только 5 фрагментов / 115 слов / 3 ранее просмотренные группы. Это описательная '
        'оценка, недостаточная для приёмки. Вырожденный RU-интервал с одной группой '
        'не даёт надёжной оценки неопределённости.', '',
        '## Проверки и ограничения', '',
        '868 новых GPU ASR-вызовов, 4 CPU smoke (EN и RU для обеих точек), 40 тестов. '
        'Сеть выключена; inference не получает эталоны. Исходные volumes только для чтения. '
        'Hash-проверки, effective options и PCM связывают ответы с теми же входами. '
        'Для старых ответов без runtime PCM отдельно записана реконструкция из исходного файла, '
        'не выдаваемая за исторически записанный checksum.', '',
        'PowerShell/Linux пересчёт: cross-platform-replay.json. Per-sample S/D/I: scored-counts.json. '
        'Параллельные ASR-процессы не используются для заявления о скорости.', '',
        'Не хватает независимых ≥300 кабинных фрагментов / ≥3000 слов / ≥20 групп, '
        '100 проверенных сущностей, а также event/temporal разметки для NLP. '
        'RU/mixed cockpit не подтверждены общим RU-контролем. Пороги ACCEPTANCE не менялись, '
        'исходный release dev-search остаётся исчерпанным, промежуточная точка не выбрана задним числом. '
        'Разные адаптированные веса не являются сравнением pipeline-добавок на одном checkpoint. '
        'В рабочем сервисе сохранена исходная модель.', '',
        '[Протокол](protocol.md) · [Метрики](comparison.json) · [Проверки](summary.json) · '
        '[Команды](../../docs/nus_decoder.md)', '']
    if (root / 'report.md').exists():
        raise ValueError('Preserve existing report')
    (root / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({k: summary[k] for k in ('artifact_verification', 'release', 'new_GPU_ASR_calls', 'new_CPU_ASR_calls')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/report'))
    main(parser.parse_args().root)
