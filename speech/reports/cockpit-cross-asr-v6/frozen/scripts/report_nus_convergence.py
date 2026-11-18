"""Summarize executed convergence artifacts without making release claims."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.metrics import lexical_normalizer_v1
from scripts.nus_convergence import read, save_new


def main(root):
    plan, fit = read(root / 'plan.json'), read(root / 'fit-comparison.json')
    training, conversion = read(root / 'training.json'), read(root / 'conversion.json')
    inputs, refs = read(root / 'inputs.json'), read(root / 'scoring/references.json')
    from north55_speech.core import file_hash
    if any(value['plan_sha256'] != file_hash(root / 'plan.json') for value in (fit, training, conversion)):
        raise ValueError('Artifact plan identity differs')
    if file_hash(root / 'inputs.json') != plan['inputs_sha256'] or file_hash(root / 'scoring/references.json') != plan['scoring_sha256']['references.json']:
        raise ValueError('Input/reference integrity differs')
    selected_texts = {lexical_normalizer_v1(refs[i['reference_id']]) for i in inputs['fit']}
    remaining = [i for i in inputs['transfer'] if i['cohort'] == 'nus_same_source_nonfit']
    overlap = sum(lexical_normalizer_v1(refs[i['reference_id']]) in selected_texts for i in remaining)
    transfer = read(root / 'transfer-comparison.json') if fit['decision']['run_transfer'] else None
    if transfer and transfer['plan_sha256'] != file_hash(root / 'plan.json'):
        raise ValueError('Transfer identity differs')
    executions = {str(p.relative_to(root)): read(p) for p in root.glob('*/execution.json')}
    tests = list(ET.parse(root / 'tests/results.xml').getroot().iter('testsuite'))
    test_counts = {k: sum(int(s.attrib.get(k, 0)) for s in tests) for k in ('tests', 'failures', 'errors', 'skipped')}
    runtime = [read(p) for p in root.glob('north55-*.json')]
    inference = [r for r in runtime if r['command'][3:4] in (['fit'], ['transfer'], ['cpu'])]
    checks = {
        '240_optimizer_steps': training['global_steps'] == 240,
        'exact_32_originals': set(training['coverage']) == set(plan['selected_ids']),
        'all_milestones_saved': set(training['checkpoints']) == {'40', '120', '240'},
        'all_milestones_converted': set(conversion['models']) == {'40', '120', '240'},
        'unit_tests_passed': test_counts['tests'] == 8 and not any(test_counts[k] for k in ('failures', 'errors', 'skipped')),
        'inference_recorded': len(inference) >= 4,
        'inference_offline': bool(inference) and all(r['network'] == 'none' for r in inference),
        'no_references_in_generation': bool(inference) and all(not any(m['Destination'] in ('/study', '/train/subset.jsonl') or '/scoring' in m['Destination'] for m in r['mounts']) for r in inference),
        'source_models_audio_readonly': all(not m['RW'] for r in runtime for m in r['mounts'] if m['Destination'] in ('/models', '/audio')),
        'zero_ASR_runtime_failures': all(not r['runtime_failures'] for r in executions.values()),
        'CPU_smoke_completed': any(k.startswith('cpu-fit-240/') and v['actual_device'] == 'cpu' and not v['runtime_failures'] for k, v in executions.items()),
        'correct_conditional_transfer': (root / 'transfer-comparison.json').exists() == fit['decision']['run_transfer'],
    }
    if (root / 'cross-platform-replay.json').exists():
        checks['linux_replay'] = read(root / 'cross-platform-replay.json')['status'] == 'PASS'
    summary = {'implemented': True, 'executed': True,
        'artifact_verification': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
        'train_fit': fit['decision']['train_fit'], 'learning_curve': fit['curve'],
        'training_steps': training['global_steps'], 'training_originals': 32,
        'training_minutes': plan['fit_duration_sec']/60, 'training_words': fit['curve']['0']['N'],
        'loader_positions': sum(training['coverage'].values()), 'test_accessed': False,
        'transfer_status': 'EXECUTED' if transfer else 'NOT_RUN_BY_FROZEN_CONDITION',
        'remaining_NUS_text_overlap': {'same_normalized_text_as_fit': overlap, 'remaining_total': len(remaining),
            'independent_validation': False, 'speaker_ids_known': False, 'original_source_groups': 1},
        'new_GPU_ASR_calls': sum(r['new_ASR_calls'] for r in executions.values() if r['actual_device'] == 'cuda'),
        'new_CPU_ASR_calls': sum(r['new_ASR_calls'] for r in executions.values() if r['actual_device'] == 'cpu'),
        'release': transfer['release'] if transfer else 'NEEDS_MORE_DATA', 'release_promoted': False,
        'independent_quality': 'NEEDS_MORE_DATA', 'tests': test_counts,
        'plan_sha256': file_hash(root / 'plan.json'), 'training_sha256': file_hash(root / 'training.json'),
        'fit_comparison_sha256': file_hash(root / 'fit-comparison.json'),
        'report_script_sha256': file_hash(Path(__file__))}
    save_new(root / 'summary.json', summary)
    lines = ['# NUS: контрольное обучение на 32 парах', '',
        f"Проверка усвоения train: **{summary['train_fit']}**. Проверка артефактов: **{summary['artifact_verification']}**.", '',
        f"32 готовые NUS-пары, {summary['training_minutes']:.3f} мин, {summary['training_words']} lexical words. "
        'Исходные тексты не менялись; одна исходная группа, неизвестные говорящие.', '',
        '| Шаг | WER своих обучающих примеров | S | D | I |', '|---|---:|---:|---:|---:|']
    for step, value in fit['curve'].items():
        lines.append(f"| {step} | {value['wer_lexical_corpus']*100:.2f}% | {value['S']} | {value['D']} | {value['I']} |")
    lines += ['', 'Это самостоятельное распознавание сохранённых CT2 float16-весов с обычным timestamp decoder. '
        'Шаг 0 — проверенные исторические ответы исходной модели. Loss обучения не подменяет WER. '
        'Промежуточный checkpoint не выбирался по результатам.', '',
        f"Выполнено 240 шагов, {summary['loader_positions']} позиций загрузчика; nominal 30 эпох. "
        'Одна траектория обучения, без dev early stopping и изменения LR между опытами. '
        'Оптимизатор/расписание/параметры LoRA сохранены в training.json.', '',
        '## Другие записи', '']
    if transfer:
        lines += ['| Набор | Parent WER | Step 240 WER |', '|---|---:|---:|']
        for cohort, value in transfer['cohorts'].items():
            if cohort not in ('noise_only', 'bleriot_b_noise'):
                lines.append(f"| {cohort} | {value['parent']['wer_lexical_corpus']*100:.2f}% | {value['final']['wer_lexical_corpus']*100:.2f}% |")
        lines += ['', '| Неречевые записи | Parent вставок/мин | Step 240 вставок/мин |', '|---|---:|---:|']
        for cohort in ('noise_only', 'bleriot_b_noise'):
            value = transfer['cohorts'][cohort]
            lines.append(f"| {cohort} | {value['parent_insertions_per_minute']:.3f} | {value['final_insertions_per_minute']:.3f} |")
        lines += ['', f"Контрольные проверки: `{json.dumps(transfer['checks'], ensure_ascii=False)}`.",
            'Bootstrap для доступных dev-групп сохранён в transfer-comparison.json; это exploratory, '
            'пять человеческих кабинных фрагментов не дают независимой приёмки.']
    else:
        lines += ['Условие final train WER ≤ 10% не выполнено. По зафиксированному протоколу '
                  'перенос на другие записи не оценивался; дополнительное обучение не запускалось.']
    lines += ['', f'В оставшихся 243 NUS-фрагментах {overlap} имеют тот же нормализованный текст, '
        'что один из 32 fit-примеров. Все они принадлежат прежней общей train-группе; '
        'называть это независимым validation/test нельзя.', '',
        '## Исполнение и ограничения', '',
        f"Новых GPU-ответов: {summary['new_GPU_ASR_calls']}; CPU smoke: {summary['new_CPU_ASR_calls']}; 8 тестов. "
        'Первый запуск остановился до trainer.train из-за владельца нового пустого volume. '
        'После назначения uid/gid 10001 тот же протокол выполнен; исходный отказ сохранён. '
        'Прежние модельные volumes и аудио монтировались только для чтения.', '',
        'Сходимость на собственном train не подтверждает качество текста источника и перенос в кабину. '
        'Исследовательская цель 10% с независимым статистическим подтверждением, сущности, NLP/temporal '
        'и качество RU/mixed cockpit остаются неподтверждёнными. Никакой candidate не продвинут.', '',
        '[Протокол и assumptions](protocol.md) · [Измерения](summary.json) · '
        '[Команды](../../docs/nus_convergence.md)', '']
    (root / 'report.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({k: summary[k] for k in ('artifact_verification', 'train_fit', 'transfer_status', 'new_GPU_ASR_calls', 'new_CPU_ASR_calls', 'release')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/report'))
    main(parser.parse_args().root)
