"""Integrity-checked diagnosis; fitting is explicitly excluded from quality claims."""

import json
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.metrics import corpus_counts, edit_counts, paired_cluster_bootstrap
from scripts.nus_failure_diagnosis import validate

ROOT = Path('/study')
SYSTEMS = ('parent_on', 'parent_off', 'nus_on', 'nus_off')


def read(path):
    return json.loads(path.read_bytes())


def load_records(stage, system, items, plan, cpu=False):
    folder = ROOT / (('cpu-' if cpu else '') + stage + '-' + system)
    execution = read(folder / 'execution.json')
    if execution['plan_sha256'] != file_hash(ROOT / 'plan.json'):
        raise ValueError('Execution identity differs')
    if set(execution['prediction_sha256']) != {i['id'] + '.json' for i in items}:
        raise ValueError('Incomplete or unexpected prediction population')
    config = plan['configs'][system] | ({'device': 'cpu', 'compute_type': 'int8'} if cpu else {})
    records = {}
    for item in items:
        path = folder / 'predictions' / (item['id'] + '.json')
        if file_hash(path) != execution['prediction_sha256'][path.name]:
            raise ValueError('Prediction hash changed')
        record = read(path)
        if (record['plan_sha256'] != execution['plan_sha256'] or record['config'] != config
                or any(record[k] != v for k, v in item.items())):
            raise ValueError('Prediction/request mismatch')
        if record['runtime_failure'] is not None and record['hypothesis']:
            raise ValueError('Failure must have empty hypothesis')
        if record['effective_options']['condition_on_previous_text'] != system.endswith('_on'):
            raise ValueError('Context factor not applied')
        records[item['id']] = record
    for name, expected in execution['runtime_sha256'].items():
        if file_hash(folder / name) != expected:
            raise ValueError('Runtime changed')
        runtime = read(folder / name)
        if (runtime['status'] != 'COMPLETED' or runtime['actual_device'] != ('cpu' if cpu else 'cuda')
                or runtime['actual_precision'] != ('int8_float32' if cpu else 'float16')):
            raise ValueError('Runtime did not complete at expected precision')
    return records


def aggregate(items, refs, lookup):
    eligible = [i for i in items if refs[i['reference_id']] is not None]
    counts = {s: {i['id']: edit_counts(refs[i['reference_id']], records[i['id']]['hypothesis'])
                  for i in eligible} for s, records in lookup.items()}
    return {'inputs': len(items), 'scored_inputs': len(eligible), 'groups': len({i['group_id'] for i in eligible}),
            'scores': {s: corpus_counts(list(values.values())) for s, values in counts.items()}}, counts


def main():
    plan = validate()
    inputs = read(ROOT / 'inputs.json')
    for name, expected in plan['scoring_sha256'].items():
        if file_hash(ROOT / 'scoring' / name) != expected:
            raise ValueError('Frozen references or historical answers changed')
    refs = read(ROOT / 'scoring/dev-references.json')
    fit_refs = read(ROOT / 'scoring/fit-references.json')
    historical = {s: read(ROOT / 'scoring' / (s + '.json')) for s in ('parent', 'nus')}
    traces = {s: load_records('trace', s, inputs['trace'], plan) for s in SYSTEMS}
    fit = {s: load_records('fit', s, inputs['fit'], plan) for s in ('parent_on', 'nus_on')}
    cpu = {s: load_records('trace', s, inputs['trace'][:1], plan, cpu=True) for s in SYSTEMS}
    checks = {}
    for base in ('parent', 'nus'):
        checks[base + '_instrumented_replay_matches_history'] = all(
            traces[base + '_on'][i['id']]['hypothesis'] == historical[base][i['id']]['hypothesis'] and
            traces[base + '_on'][i['id']]['effective_options'] == historical[base][i['id']]['effective_options'] and
            traces[base + '_on'][i['id']]['effective_waveform_sha256'] == historical[base][i['id']]['effective_waveform_sha256']
            for i in inputs['trace'])
        checks[base + '_only_context_flag_changes'] = all(
            traces[base + '_on'][i['id']]['effective_options'] |
            {'condition_on_previous_text': False} == traces[base + '_off'][i['id']]['effective_options']
            for i in inputs['trace'])
    changed = {base: [i['id'] for i in inputs['trace'] if traces[base + '_on'][i['id']]['hypothesis'] !=
                     traces[base + '_off'][i['id']]['hypothesis']] for base in ('parent', 'nus')}
    checks['GPU_records_successful'] = all(r['runtime_failure'] is None for lookup in (traces, fit)
                                         for records in lookup.values() for r in records.values())
    checks['CPU_smokes_successful'] = all(r['runtime_failure'] is None for records in cpu.values() for r in records.values())
    trace_details = []
    for item in inputs['trace']:
        for system, records in traces.items():
            record = records[item['id']]
            trace_details.append({'id': item['id'], 'cohort': item['cohort'], 'system': system,
                                  'counts': edit_counts(refs[item['reference_id']], record['hypothesis']),
                                  'decode_calls': len(record['trace']),
                                  'calls': [{k: c.get(k) for k in ('index', 'previous_token_count', 'input_seek_frames',
                                             'time_offset_sec', 'segment_duration_sec', 'seek_after_split_frames',
                                             'single_timestamp_ending')} for c in record['trace']]})
    fit_summary, fit_counts = aggregate(inputs['fit'], fit_refs, fit)
    base_wer, new_wer = (fit_summary['scores'][s]['wer_lexical_corpus'] for s in ('parent_on', 'nus_on'))
    fit_summary.update(wer_delta=new_wer - base_wer, relative_reduction=(base_wer - new_wer)/base_wer if base_wer else None,
                       scope='Training fitting only; all references weak, one group, no generalization or quality CI.')
    trace_cohorts = {c: aggregate([i for i in inputs['trace'] if i['cohort'] == c], refs, traces)[0]
                     for c in ('partial_human_dev', 'quiet_partial_human_dev')}
    context = {'status': 'NOT_RUN', 'reason': 'Protocol skips expansion when no trace hypothesis changes.'}
    if any(changed.values()):
        off = {s: load_records('context', s, inputs['context'], plan) for s in ('parent_off', 'nus_off')}
        lookup = off | {s + '_on': records for s, records in historical.items()}
        cohorts = {}
        for cohort in sorted({i['cohort'] for i in inputs['context']}):
            members = [i for i in inputs['context'] if i['cohort'] == cohort]
            summary, counts = aggregate(members, refs, lookup)
            summary['paired_changes'] = {}
            for base in ('parent', 'nus'):
                a, b = (summary['scores'][base + '_' + mode]['wer_lexical_corpus'] for mode in ('on', 'off'))
                eligible = [i for i in members if refs[i['reference_id']] is not None]
                summary['paired_changes'][base] = {'wer_delta': b-a if a is not None and b is not None else None,
                    'relative_reduction': (a-b)/a if a else None,
                    'bootstrap': paired_cluster_bootstrap([{'group_id': i['group_id'], 'baseline': counts[base+'_on'][i['id']],
                       'candidate': counts[base+'_off'][i['id']]} for i in eligible], resamples=2000, seed=55, confidence=.95)}
            if cohort in ('noise_only', 'bleriot_b_noise'):
                minutes = sum(i['duration_sec'] for i in members)/60
                summary['inserted_words_per_minute'] = {s: sum(v['I'] for v in counts[s].values())/minutes for s in lookup}
            cohorts[cohort] = summary
        checks['context_GPU_records_successful'] = all(r['runtime_failure'] is None for records in off.values() for r in records.values())
        context = {'status': 'EXECUTED', 'cohorts': cohorts}
    # Evidence of container isolation must be independently readable in the report.
    runtimes = [read(p) for p in ROOT.glob('north55-*.json')]
    inference = [r for r in runtimes if r['command'][:3] == ['-u', '-m', 'scripts.nus_failure_diagnosis']]
    checks['inference_containers_recorded'] = bool(inference)
    checks['offline_inference'] = all(r['network_mode'] == 'none' for r in inference)
    checks['no_references_in_inference_mounts'] = all(not any('/scoring' in m['Destination'] or
          m['Destination'] == '/study' for m in r['mounts']) for r in inference)
    checks['audio_models_readonly'] = all(not m['RW'] for r in inference for m in r['mounts'] if m['Destination'] in ('/audio', '/models'))
    result = {'artifact_status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
              'plan_sha256': file_hash(ROOT / 'plan.json'), 'trace_changes': changed, 'trace_cohorts': trace_cohorts,
              'fit': fit_summary, 'context': context, 'test_accessed': False, 'release_promoted': False,
              'quality_evidence': False, 'release': 'FAIL', 'independent_quality': 'NEEDS_MORE_DATA',
              'new_GPU_predictions': sum(len(v) for v in traces.values()) + sum(len(v) for v in fit.values()) +
                   (2 * len(inputs['context']) if context['status'] == 'EXECUTED' else 0),
              'new_CPU_predictions': sum(len(v) for v in cpu.values())}
    atomic_json(ROOT / 'comparison.json', result)
    atomic_json(ROOT / 'trace-counts.json', trace_details)
    atomic_json(ROOT / 'fit-counts.json', fit_counts)
    print(json.dumps({k: result[k] for k in ('artifact_status', 'checks', 'trace_changes', 'fit', 'new_GPU_predictions', 'new_CPU_predictions')}))


if __name__ == '__main__':
    main()
