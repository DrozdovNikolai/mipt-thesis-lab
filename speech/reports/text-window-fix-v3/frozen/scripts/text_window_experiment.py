"""Fixed replay of the completed-window repair, without training or release choice."""

import argparse
import json
from pathlib import Path

from north55_speech.core import atomic_json, file_hash, now
from north55_speech.metrics import corpus_counts, edit_counts, paired_cluster_bootstrap
from north55_speech.text_windows import (
    LOOP_SHA256,
    TAIL_VAD,
    VAD_FINALIZATION_SAMPLES,
    verify_backend,
)
from scripts import decoding_diagnostics as d

SYSTEMS = ('parent_reference', 'parent_text', 'augmented_reference', 'augmented_text')
ROOT = Path('/study')


def prepare():
    if (ROOT / 'plan.json').exists():
        raise ValueError('Existing study is immutable')
    verify_backend()
    old = d.read(Path('/prior/plan.json'))
    if file_hash(Path('/prior/inputs.json')) != old['inputs_sha256']:
        raise ValueError('Previous inputs changed')
    items = d.read(Path('/prior/inputs.json'))
    configs = {s: old['configs'][s.replace('_reference', '_baseline')] for s in SYSTEMS}
    for model in ('parent', 'augmented'):
        baseline_path = Path('/prior/controls') / (model + '.json')
        if file_hash(baseline_path) != old['controls_sha256'][model]:
            raise ValueError('Historical control changed')
        baseline = d.read(baseline_path)
        for mode in ('baseline', 'text'):
            output = Path('/prior') / (model + '_' + mode)
            execution = d.read(output / 'execution.json')
            if execution['plan_sha256'] != file_hash(Path('/prior/plan.json')):
                raise ValueError('Historical execution plan changed')
            records = {}
            for filename, expected in execution['prediction_sha256'].items():
                path = output / 'predictions' / filename
                if file_hash(path) != expected:
                    raise ValueError('Historical prediction changed')
                record = d.read(path)
                records[record['id']] = record
            if mode == 'baseline':
                baseline.update(records)
                records = baseline
            if set(records) != {i['id'] for i in items}:
                raise ValueError('Historical population differs')
            atomic_json(ROOT / 'historical' / f'{model}_{mode}.json', records)
    atomic_json(ROOT / 'inputs.json', items)
    if file_hash(ROOT / 'inputs.json') != old['inputs_sha256']:
        raise ValueError('Input bytes must be identical to decoding-v1')
    atomic_json(ROOT / 'plan.json', {**d.identity(), 'repair_driver_sha256': file_hash(Path(__file__)),
        'frozen_at': now().isoformat(), 'previous_plan_sha256': file_hash(Path('/prior/plan.json')),
        'backend_loop_sha256': LOOP_SHA256, 'references_sha256': old['references_sha256'],
        'inputs_sha256': old['inputs_sha256'], 'input_count': len(items),
        'configs': configs, 'models': old['models'], 'systems': list(SYSTEMS),
        'options_overrides': {s: {'without_timestamps': s.endswith('_text')} for s in SYSTEMS},
        'historical_sha256': {p.stem: file_hash(p) for p in (ROOT / 'historical').glob('*.json')},
        'new_configurations': 2, 'previous_configurations': 26, 'cumulative_configurations': 28,
        'vad_only_finalization_samples': VAD_FINALIZATION_SAMPLES,
        'first_repair_plan_sha256': file_hash(Path('/first-repair-plan.json')),
        'tail_speech_guard': TAIL_VAD, 'strategy': 'Retain ordinary cursor advance only when unconsumed speech remains; no input cropping.',
        'authorization': 'User explicitly requested the completed-window repair and its comparison; two fixed repaired checkpoints, no search.',
        'training_runs': 0, 'test_accessed': False, 'release_promoted': False,
        'limitations': old['limitations'] + ['A repair of the broken text mode is not automatically an improvement over the proper baseline.']})
    print(json.dumps({'status': 'FROZEN', 'inputs': len(items), 'new_configurations': 2}))


def validate():
    plan = d.validate()
    if plan['repair_driver_sha256'] != file_hash(Path(__file__)):
        raise ValueError('Repair driver changed after freeze')
    verify_backend()
    return plan


def paired(items, lookup, baseline, candidate):
    a = corpus_counts([lookup[baseline, i['id']]['score'] for i in items])
    b = corpus_counts([lookup[candidate, i['id']]['score'] for i in items])
    x, y = a['wer_lexical_corpus'], b['wer_lexical_corpus']
    return {'baseline': baseline, 'candidate': candidate,
            'wer_delta': y - x if x is not None else None,
            'relative_reduction': (x - y) / x if x else None,
            'bootstrap': paired_cluster_bootstrap([{'group_id': i['group_id'],
                'baseline': lookup[baseline, i['id']]['score'], 'candidate': lookup[candidate, i['id']]['score']}
                for i in items], resamples=2000, seed=55, confidence=.95)}


def score():
    plan = validate()
    if file_hash(Path('/scoring/references.json')) != plan['references_sha256']:
        raise ValueError('Reference checksum differs')
    refs, items = d.read(Path('/scoring/references.json')), d.read(ROOT / 'inputs.json')
    lookup, runtimes = {}, {}
    for name, expected in plan['historical_sha256'].items():
        path = ROOT / 'historical' / (name + '.json')
        if file_hash(path) != expected:
            raise ValueError('Historical results changed')
        lookup.update({('old_' + name, k): v for k, v in d.read(path).items()})
    for system in SYSTEMS:
        output = ROOT / system
        execution = d.read(output / 'execution.json')
        if execution['plan_sha256'] != file_hash(ROOT / 'plan.json') or set(execution['prediction_sha256']) != {i['id'] + '.json' for i in items}:
            raise ValueError('Execution population differs')
        for filename, expected in execution['prediction_sha256'].items():
            path = output / 'predictions' / filename
            if file_hash(path) != expected:
                raise ValueError('Prediction changed')
            r = d.read(path)
            if r['plan_sha256'] != execution['plan_sha256']:
                raise ValueError('Prediction plan differs')
            lookup[system, r['id']] = r
        runtimes[system] = []
        for filename, expected in execution['runtime_sha256'].items():
            if file_hash(output / filename) != expected:
                raise ValueError('Runtime changed')
            runtimes[system].append(d.read(output / filename))
    all_systems = (*SYSTEMS, *(f'old_{m}_{v}' for m in ('parent', 'augmented') for v in ('baseline', 'text')))
    rows = []
    for system in all_systems:
        for item in items:
            r = lookup[system, item['id']]
            if r['audio_sha256'] != item['audio_sha256']:
                raise ValueError('Audio mismatch')
            ref = refs[item['reference_id']]
            if ref is None:
                raise ValueError('Unexpected missing reference')
            r['score'] = edit_counts(ref, r['hypothesis'])
            rows.append({'id': item['id'], 'system': system, 'group_id': item['group_id'],
                         'cohort': item['cohort'], 'score': r['score'], 'runtime_failure': r['runtime_failure']})
    membership = {c: [i for i in items if i['cohort'] == c] for c in sorted({i['cohort'] for i in items})}
    membership['short_general_clean'] = [i for i in items if i['cohort'] == 'general_clean' and i['duration_sec'] <= 4]
    cohorts = {}
    for cohort, members in membership.items():
        minutes = sum(i['duration_sec'] for i in members) / 60
        cohorts[cohort] = {'inputs': len(members), 'groups': len({i['group_id'] for i in members}),
            'channel_minutes': minutes, 'systems': {s: {
                'counts': corpus_counts([lookup[s, i['id']]['score'] for i in members]),
                'empty_hypotheses': sum(not lookup[s, i['id']]['hypothesis'].strip() for i in members),
                'inserted_words_per_minute': sum(lookup[s, i['id']]['score']['I'] for i in members) / minutes}
                for s in all_systems}, 'comparisons': {f'{m}_{kind}': paired(members, lookup,
                    f'{m}_reference' if kind == 'vs_baseline' else f'old_{m}_text', f'{m}_text')
                    for m in ('parent', 'augmented') for kind in ('vs_baseline', 'vs_broken')}}
    replay = {m: {'inputs': len(items), 'same_hypotheses': sum(lookup[f'{m}_reference', i['id']]['hypothesis'] == lookup[f'old_{m}_baseline', i['id']]['hypothesis'] for i in items),
                   'same_options': all(lookup[f'{m}_reference', i['id']]['effective_options'] == lookup[f'old_{m}_baseline', i['id']]['effective_options'] for i in items)} for m in ('parent', 'augmented')}
    failures = {s: sum(lookup[s, i['id']]['runtime_failure'] is not None for i in items) for s in SYSTEMS}
    gates = {}
    for model in ('parent', 'augmented'):
        primary = cohorts['partial_human_dev']['comparisons'][model + '_vs_baseline']
        target = primary['relative_reduction'] >= .1
        clean = cohorts['general_clean']['comparisons'][model + '_vs_baseline']['wer_delta'] <= .01
        ru = cohorts['general_ru']['comparisons'][model + '_vs_baseline']['wer_delta'] <= .01
        noise = all(cohorts[c]['systems'][model + '_text']['inserted_words_per_minute'] <=
                    cohorts[c]['systems'][model + '_reference']['inserted_words_per_minute'] for c in ('noise_only', 'bleriot_b_noise'))
        gates[model] = {'human_dev_point_target': 'PASS' if target else 'FAIL',
            'clean_guard': 'PASS' if clean else 'FAIL', 'ru_guard': 'PASS' if ru else 'FAIL',
            'noise_guard': 'PASS' if noise else 'FAIL',
            'runtime_guard': 'PASS' if failures[model + '_text'] == 0 else 'FAIL',
            'paired_ci_excludes_zero': primary['bootstrap']['upper'] < 0,
            'statistical_confirmation': 'INCONCLUSIVE', 'critical_entities': 'NEEDS_MORE_DATA',
            'release': 'FAIL' if not all((target, clean, ru, noise, failures[model + '_text'] == 0)) else 'NEEDS_MORE_DATA'}
    result = {'status': 'EXECUTED_DIAGNOSTIC', 'plan_sha256': file_hash(ROOT / 'plan.json'),
        'new_predictions': 4 * len(items), 'historical_records': 4 * len(items), 'cohorts': cohorts,
        'baseline_replay': replay, 'gates': gates, 'runtime_failures': failures,
        'alignment': {s: {'nonempty_segments_without_words': sum(lookup[s, i['id']]['alignment']['nonempty_segments_without_words'] for i in items),
                         'zero_duration_words': sum(lookup[s, i['id']]['alignment']['zero_duration_words'] for i in items)} for s in SYSTEMS},
        'actual_precisions': {s: sorted({r['actual_precision'] for r in rs}) for s, rs in runtimes.items()},
        'test_accessed': False, 'release_promoted': False, 'asr_quality_gate': 'NEEDS_MORE_DATA',
        'limitations': plan['limitations']}
    atomic_json(ROOT / 'scored-counts.json', rows)
    atomic_json(ROOT / 'comparison.json', result)
    print(json.dumps({'gates': gates, 'baseline_replay': replay, 'runtime_failures': failures}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'infer', 'cpu', 'score'))
    parser.add_argument('--system', choices=SYSTEMS)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'score':
        score()
    else:
        validate()
        if not args.system:
            parser.error('--system required')
        d.infer(args.system, cpu=args.action == 'cpu')
