"""Score retained train-only answers without changing any labels or quality gates."""

import json
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.metrics import corpus_counts, edit_counts
from scripts.audit_nus_training_contract import read, save, sha

REPO = Path('/work')
ROOT = REPO / 'reports/nus-training-contract-v1'
OUT = Path('/report')


def main():
    plan = read(ROOT / 'plan.json')
    freeze = read(ROOT / 'scorer-freeze-v2.json')
    if sha(Path(__file__)) != freeze['script_sha256']:
        raise ValueError('Scorer changed')
    if sha(Path('/app/src/north55_speech/metrics.py')) != freeze['metrics_sha256']:
        raise ValueError('Lexical metric changed')
    train = REPO / 'data/curated/nus-training-v1/train.jsonl'
    if sha(train) != plan['train_sha256'] or sha(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Training inputs changed')
    samples = [json.loads(line) for line in train.read_text(encoding='utf-8').splitlines()]
    references = {s['sample_id']: s['reference_text'] for s in samples}
    prior = REPO / 'reports/nus-diagnosis-v1'
    historical = read(prior / 'plan.json')
    if historical['train_manifest_sha256'] != plan['train_sha256']:
        raise ValueError('Historical population differs')
    counts, failures, case_changes = {}, {}, {}
    for system in ('parent', 'nus'):
        execution = read(ROOT / system / 'execution.json')
        if execution['plan_sha256'] != sha(ROOT / 'plan.json'):
            raise ValueError('Execution plan differs')
        old_dir = prior / ('fit-' + system + '_on')
        old_run = read(old_dir / 'execution.json')
        if old_run['plan_sha256'] != sha(prior / 'plan.json'):
            raise ValueError('Historical execution differs')
        before, after, changes = [], [], {'better': 0, 'worse': 0, 'same': 0}
        failed = []
        for item in read(ROOT / 'inputs.json'):
            filename = item['id'] + '.json'
            path = ROOT / system / 'predictions' / filename
            old_path = old_dir / 'predictions' / filename
            if sha(path) != execution['prediction_sha256'][filename] or sha(old_path) != old_run['prediction_sha256'][filename]:
                raise ValueError('Prediction changed')
            old, current = read(old_path), read(path)
            if any(current[k] != v or old[k] != v for k, v in item.items()):
                raise ValueError('Prediction input differs')
            if current['effective_options'] != old['effective_options'] | {'without_timestamps': True}:
                raise ValueError('More than the declared decoding factor changed')
            if current.get('effective_waveform_sha256') != old['effective_waveform_sha256']:
                raise ValueError('Effective audio differs')
            if current['runtime_failure'] is not None:
                failed.append(item['id'])
            if old['runtime_failure'] is not None:
                raise ValueError('Historical failure needs explicit handling')
            before.append(edit_counts(references[item['id']], old['hypothesis']))
            after.append(edit_counts(references[item['id']], current['hypothesis'] if current['runtime_failure'] is None else ''))
            delta = sum(after[-1][k] - before[-1][k] for k in ('S', 'D', 'I'))
            changes['better' if delta < 0 else 'worse' if delta > 0 else 'same'] += 1
        counts[system] = {'timestamp_enabled': corpus_counts(before), 'text_only': corpus_counts(after)}
        failures[system], case_changes[system] = failed, changes
    repaired_plan = read(ROOT / 'contract-repair/plan.json')
    if (repaired_plan | {'script_sha256': plan['script_sha256']}) != plan:
        raise ValueError('Contract retry changed more than the audited implementation')
    contract = read(ROOT / 'contract-retry/contract.json')
    if contract['plan_sha256'] != sha(ROOT / 'contract-repair/plan.json'):
        raise ValueError('Contract retry identity differs')
    merge = read(ROOT / 'contract-retry/merge.json')
    teacher = read(ROOT / 'contract-retry/teacher-forcing.json')
    loss = {}
    for system in ('parent', 'nus'):
        rows = [r for r in teacher if r['system'] == system]
        loss[system] = {k: statistics.mean(r[k] for r in rows) for k in ('matching_audio', 'different_audio')}
        loss[system]['matching_audio_lower_loss_cases'] = sum(r['matching_audio'] < r['different_audio'] for r in rows)
    tests = list(ET.parse(ROOT / 'tests/tests.xml').getroot().iter('testsuite'))
    test_counts = {k: sum(int(s.attrib.get(k, 0)) for s in tests) for k in ('tests', 'failures', 'errors', 'skipped')}
    result = {'kind': 'training_contract_diagnosis', 'implemented': True, 'executed': True,
              'mechanical_contract': contract['status'], 'merge': merge,
              'audio_token_pairs': contract['audio_token_pairs'], 'maximum_mel_difference': contract['maximum_mel_difference'],
              'train_lexical_WER': counts, 'timestamp_factor_case_changes': case_changes,
              'teacher_forced_mean_loss': loss, 'teacher_forced_cases_per_model': 32,
              'new_ASR_calls': 550, 'new_training_steps': 0, 'runtime_failures': failures, 'tests': test_counts,
              'test_accessed': False, 'human_audio_verification': False, 'labels_changed': False,
              'candidate_selection': False, 'release_promoted': False, 'quality_gate': 'NEEDS_MORE_DATA',
              'plan_sha256': sha(ROOT / 'plan.json'), 'scorer_sha256': sha(Path(__file__)),
              'metrics_sha256': freeze['metrics_sha256'],
              'evidence_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in [
                  ROOT / 'contract-retry/contract.json', ROOT / 'contract-retry/merge.json',
                  ROOT / 'contract-retry/audio-tokens.json', ROOT / 'contract-retry/teacher-forcing.json',
                  ROOT / 'parent/execution.json', ROOT / 'nus/execution.json', ROOT / 'tests/tests.xml']}}
    save(OUT / 'comparison.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
