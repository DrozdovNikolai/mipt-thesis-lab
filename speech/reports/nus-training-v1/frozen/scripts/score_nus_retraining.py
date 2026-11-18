"""Frozen scoring recipe for one NUS checkpoint and two references."""

import json
from collections import Counter
from pathlib import Path

from north55_speech.core import file_hash
from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    lexical_normalizer_v1,
    paired_cluster_bootstrap,
)

ROOT = Path('/eval')
SYSTEMS = ('parent', 'balanced', 'nus')


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def main():
    plan = read(ROOT / 'plan.json')
    refs_path = Path('/scoring/references.json')
    if file_hash(refs_path) != plan['references_sha256'] or file_hash(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Frozen inputs or references changed')
    refs, items = read(refs_path), read(ROOT / 'inputs.json')
    lookup = {}
    for system in ('parent', 'balanced'):
        path = ROOT / 'historical' / (system+'.json')
        if file_hash(path) != plan['historical_sha256'][system]:
            raise ValueError('Historical answers changed')
        lookup[system] = read(path)
    execution = read(ROOT / 'nus/execution.json')
    if execution['plan_sha256'] != file_hash(ROOT / 'plan.json') or len(execution['prediction_sha256']) != len(items):
        raise ValueError('Incomplete candidate inference')
    lookup['nus'] = {}
    for filename, expected in execution['prediction_sha256'].items():
        path = ROOT / 'nus/predictions' / filename
        if file_hash(path) != expected:
            raise ValueError('Candidate answer changed')
        record = read(path)
        if record['plan_sha256'] != execution['plan_sha256']:
            raise ValueError('Candidate identity differs')
        lookup['nus'][record['id']] = record
    for name, expected in execution['runtime_sha256'].items():
        path = ROOT / 'nus' / name
        if file_hash(path) != expected:
            raise ValueError('Runtime hash differs')
        runtime = read(path)
        if (runtime['actual_device'], runtime['actual_precision']) != ('cuda', 'float16'):
            raise ValueError('Actual inference precision differs')
    scored, counts = [], {}
    repeat_diagnostics = []
    for item in items:
        reference = refs[item['reference_id']]
        records = [lookup[s][item['id']] for s in SYSTEMS]
        options = [r['effective_options'] for r in records]
        if not all(o == options[0] and o['without_timestamps'] is False for o in options):
            raise ValueError('Compared effective decoding options differ')
        for system, record in zip(SYSTEMS, records, strict=True):
            if record['audio_sha256'] != item['audio_sha256'] or record['config'] != plan['configs'][system]:
                raise ValueError('Compared audio/checkpoint configuration differs')
            if record['runtime_failure'] is not None and record['hypothesis']:
                raise ValueError('Runtime failure must not keep a partial favorable hypothesis')
            score = edit_counts(reference, record['hypothesis']) if reference is not None else None
            counts[system, item['id']] = score
            tokens = lexical_normalizer_v1(record['hypothesis']).split()
            trigrams = Counter(tuple(tokens[i:i+3]) for i in range(max(0, len(tokens)-2)))
            repetition = sum(n-1 for n in trigrams.values() if n > 1)
            scored.append({'id': item['id'], 'cohort': item['cohort'], 'system': system,
                'group_id': item['group_id'], 'score': score, 'runtime_failure': record['runtime_failure'],
                'excess_repeated_trigrams': repetition})
            if item['cohort'] == 'partial_human_dev':
                repeat_diagnostics.append({'id': item['id'], 'system': system, 'counts': score,
                    'excess_repeated_trigrams': repetition, 'scope': 'Repeated text may be real speech; no deduplication or event claim'})
    cohorts = {}
    membership = {c: [i for i in items if i['cohort'] == c] for c in sorted({i['cohort'] for i in items})}
    membership['short_general_clean'] = [i for i in items if i['cohort'] == 'general_clean' and i['duration_sec'] <= 4]
    for cohort, selected in membership.items():
        eligible = [i for i in selected if refs[i['reference_id']] is not None]
        summaries = {s: corpus_counts([counts[s, i['id']] for i in eligible]) for s in SYSTEMS}
        comparisons = {}
        for reference_system in ('parent', 'balanced'):
            pairs = [{'group_id': i['group_id'], 'baseline': counts[reference_system, i['id']],
                      'candidate': counts['nus', i['id']]} for i in eligible]
            a, b = summaries[reference_system]['wer_lexical_corpus'], summaries['nus']['wer_lexical_corpus']
            comparisons[reference_system] = {'relative_reduction': (a-b)/a if a else None,
                'wer_delta': b-a if a is not None and b is not None else None,
                'bootstrap': paired_cluster_bootstrap(pairs, resamples=2000, seed=55, confidence=.95)}
        value = {'inputs': len(selected), 'scored_references': len(eligible),
            'groups': len({i['group_id'] for i in selected}), 'scores': summaries, 'comparisons': comparisons}
        if cohort in ('noise_only', 'bleriot_b_noise'):
            minutes = sum(i['duration_sec'] for i in selected)/60
            value.update(channel_minutes=minutes, inserted_words_per_minute={
                s: sum(len(lexical_normalizer_v1(lookup[s][i['id']]['hypothesis']).split()) for i in selected)/minutes for s in SYSTEMS})
        cohorts[cohort] = value
    failures = {s: sum(r['runtime_failure'] is not None for r in lookup[s].values()) for s in SYSTEMS}
    gates = {}
    for reference_system in ('parent', 'balanced'):
        comparison = cohorts['partial_human_dev']['comparisons'][reference_system]
        checks = {'human_dev_point_target': comparison['relative_reduction'] >= .10,
            'clean_EN_guard': cohorts['general_clean']['comparisons'][reference_system]['wer_delta'] <= .01,
            'general_RU_guard': cohorts['general_ru']['comparisons'][reference_system]['wer_delta'] <= .01,
            'noise_guard': all(c['inserted_words_per_minute']['nus'] <= c['inserted_words_per_minute'][reference_system]
                for n, c in cohorts.items() if n in ('noise_only', 'bleriot_b_noise')),
            'runtime_guard': failures['nus'] == 0}
        gates[reference_system] = {k: 'PASS' if v else 'FAIL' for k, v in checks.items()} | {
            'statistical_confirmation': 'PASS' if comparison['bootstrap']['upper'] < 0 else 'INCONCLUSIVE',
            'independent_ASR': 'NEEDS_MORE_DATA', 'critical_entities': 'NEEDS_MORE_DATA',
            'release': 'NEEDS_MORE_DATA' if all(checks.values()) else 'FAIL'}
    result = {'status': 'EXECUTED_DIAGNOSTIC', 'plan_sha256': file_hash(ROOT / 'plan.json'),
        'report_scorer_sha256': file_hash(Path(__file__)), 'new_predictions': 675, 'historical_predictions': 1350,
        'cohorts': cohorts, 'runtime_failures': failures, 'gates': gates,
        'same_checkpoint_pipeline_gain_claimed': False, 'test_accessed': False, 'release_promoted': False}
    save(ROOT / 'comparison.json', result)
    save(ROOT / 'scored-counts.json', scored)
    save(ROOT / 'human-error-counts.json', repeat_diagnostics)
    print(json.dumps({'gates': gates, 'runtime_failures': failures}))


if __name__ == '__main__':
    main()
