"""Continue one saved adapter and assess transfer regardless of memorization score."""

import argparse

from scripts import nus_convergence as worker

worker.STEPS = (160, 400)


def score():
    from north55_speech.core import file_hash
    from north55_speech.metrics import (
        canonical_normalizer_v1,
        corpus_counts,
        edit_counts,
        lexical_normalizer_v1,
        paired_cluster_bootstrap,
    )
    from scripts.research_audio_evidence import write_legacy_evidence

    root = worker.ROOT
    plan = worker.validate()
    inputs = worker.read(root / 'inputs.json')
    refs = worker.read(root / 'scoring/references.json')
    historical = worker.read(root / 'scoring/source-fit.json')
    old_fit = worker.read(root / 'scoring/previous-fit.json')
    fit = {'unadapted': old_fit['curve']['0'], 'source240': old_fit['curve']['240']}
    failures, fit_counts = {}, {}
    secondary = {}
    for step in worker.STEPS:
        _, values, failed = worker.scored('fit', step)
        fit[str(step + 240)] = corpus_counts(list(values.values()))
        fit_counts[str(step + 240)] = values
        failures['fit-' + str(step)] = failed
    # Secondary formatting probe uses the existing symmetric normalizer, never replaces lexical WER.
    for label, records in [('source240', historical), ('final640', {
            i['id']: worker.read(root / 'fit-400/predictions' / (i['id'] + '.json')) for i in inputs['fit']})]:
        secondary[label] = corpus_counts([edit_counts(canonical_normalizer_v1(refs[i['reference_id']]),
            canonical_normalizer_v1(records[i['id']]['hypothesis'])) for i in inputs['fit']])
    a, source, source_failed = worker.scored('transfer', 0)
    a2, final, final_failed = worker.scored('transfer', 400)
    if a != a2:
        raise ValueError('Parent baseline differs between transfer comparisons')
    failures.update(transfer_source=source_failed, transfer_final=final_failed)
    systems = {'parent': a, 'source240': source, 'final640': final}
    cohorts = {}
    fit_texts = {lexical_normalizer_v1(refs[i['reference_id']]) for i in inputs['fit']}
    groups = {c: [i for i in inputs['transfer'] if i['cohort'] == c] for c in {i['cohort'] for i in inputs['transfer']}}
    remaining = groups['nus_same_source_nonfit']
    groups['nus_same_text_as_fit'] = [i for i in remaining if lexical_normalizer_v1(refs[i['reference_id']]) in fit_texts]
    groups['nus_different_text_from_fit'] = [i for i in remaining if lexical_normalizer_v1(refs[i['reference_id']]) not in fit_texts]
    for cohort, items in sorted(groups.items()):
        scores = {s: corpus_counts([v[i['id']] for i in items]) for s, v in systems.items()}
        comparisons = {}
        for base in ('parent', 'source240'):
            x, y = scores[base]['wer_lexical_corpus'], scores['final640']['wer_lexical_corpus']
            value = {'wer_delta': y-x if x is not None and y is not None else None,
                     'relative_reduction': (x-y)/x if x else None}
            if cohort not in ('noise_only', 'bleriot_b_noise') and not cohort.startswith('nus_'):
                value['bootstrap'] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                    'baseline': systems[base][i['id']], 'candidate': final[i['id']]} for i in items],
                    resamples=2000, seed=55, confidence=.95)
            comparisons['final_vs_' + base] = value
        entry = {'samples': len(items), 'groups': len({i['group_id'] for i in items}),
                 'scores': scores, 'comparisons': comparisons}
        if cohort in ('noise_only', 'bleriot_b_noise'):
            minutes = sum(i['duration_sec'] for i in items)/60
            entry.update(minutes=minutes, inserted_words_per_minute={s: v['I']/minutes for s, v in scores.items()})
        cohorts[cohort] = entry
    checks = {
        'human_dev_point': cohorts['partial_human_dev']['comparisons']['final_vs_parent']['relative_reduction'] >= .10,
        'clean_EN': cohorts['general_clean']['comparisons']['final_vs_parent']['wer_delta'] <= .01,
        'general_RU': cohorts['general_ru']['comparisons']['final_vs_parent']['wer_delta'] <= .01,
        'noise': all(cohorts[c]['inserted_words_per_minute']['final640'] <= cohorts[c]['inserted_words_per_minute']['parent']
                     for c in ('noise_only', 'bleriot_b_noise')),
        'runtime': not any(failures.values()),
    }
    result = {'plan_sha256': file_hash(root / 'plan.json'), 'fit_curve': fit, 'fit_counts': fit_counts,
        'secondary_canonical_train_WER': secondary, 'transfer': cohorts, 'checks': checks,
        'runtime_failures': failures, 'fit_diagnostic': 'PASS' if fit['640']['wer_lexical_corpus'] <= .10 else 'FAIL',
        'release': 'FAIL' if not all(checks.values()) else 'NEEDS_MORE_DATA',
        'independent_quality': 'NEEDS_MORE_DATA', 'test_accessed': False, 'release_promoted': False,
        'repeated_text_nonfit_clips': len(groups['nus_same_text_as_fit']),
        'new_training_steps': 400, 'fixed_candidate_total_steps': 640,
        'source_fit_sha256': plan['scoring_sha256']['source-fit.json']}
    worker.save_new(root / 'comparison.json', result)
    write_legacy_evidence(root / 'legacy-waveform-evidence.json')
    print(worker.json.dumps({'fit_WER': {k: v['wer_lexical_corpus'] for k, v in fit.items()},
        'transfer_WER': {c: {k: v['wer_lexical_corpus'] for k, v in e['scores'].items()} for c, e in cohorts.items()},
        'checks': checks, 'release': result['release']}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['train', 'convert', 'fit', 'transfer', 'cpu', 'score-transfer'])
    parser.add_argument('step', nargs='?', type=int, choices=[0, 160, 400])
    args = parser.parse_args()
    if args.stage in ('fit', 'transfer', 'cpu'):
        if args.step is None or (args.stage != 'transfer' and args.step == 0):
            parser.error('Valid phase step is required')
        worker.infer('fit' if args.stage == 'cpu' else args.stage, args.step, cpu=args.stage == 'cpu')
    else:
        {'train': worker.train, 'convert': worker.convert, 'score-transfer': score}[args.stage]()
