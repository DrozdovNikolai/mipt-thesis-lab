"""Freeze all 1,901 ATCOSIM inputs, source references, and historical comparison runs."""
import hashlib
import json
import shutil
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    work = Path(__file__).resolve().parents[1]
    old = work/'reports/aviation-v1'
    out = work/'reports/aviation-v13'
    if out.exists():
        raise ValueError('Choose a new study directory')
    old_plan_path = old/'inference/plan.json'
    old_plan = read(old_plan_path)
    assert sha(old/'inference/inputs.json') == old_plan['inputs_sha256']
    assert sha(old/'scoring/references.json') == old_plan['references_sha256']
    previous = [r for r in read(old/'inference/inputs.json') if r['cohort'] == 'atcosim']
    assert len(previous) == len({i['id'] for i in previous}) == 1901
    references = read(old/'scoring/references.json')
    inputs, refs, cached, evidence = [], {}, {}, {}
    for item in previous:
        name = Path(item['audio_path']).name
        audio = work/'data/curated/aviation-v1/audio'/name
        assert sha(audio) == item['audio_sha256']
        inputs.append({'id': item['id'], 'file': name, 'audio_sha256': item['audio_sha256'],
                       'pcm_sha256': item['pcm_sha256'], 'duration_sec': item['duration_sec'],
                       'speaker': item['speaker_id']})
        refs[item['id']] = references[item['id']]
    for system in ['small', 'atc']:
        folder = old/'predictions'/system
        execution = read(folder/'execution.json')
        assert execution['plan_sha256'] == sha(old_plan_path)
        cached[system] = {}
        for item in previous:
            path = folder/f"{item['id']}.json"
            assert sha(path) == execution['files'][item['id']]
            row = read(path)
            assert row['plan_sha256'] == sha(old_plan_path)
            assert row['pcm_sha256'] == item['pcm_sha256'] and row['runtime_failure'] is None
            cached[system][item['id']] = row['hypothesis']
        evidence[system] = {'execution_sha256': sha(folder/'execution.json'),
                            'model': old_plan['configs'][system]['model'], 'reused_predictions': 1901}
    save(out/'inputs.json', inputs)
    save(out/'scoring/references.json', refs)
    save(out/'scoring/cached.json', cached)
    smoke = work/'reports/cockpit-reviewed-v12'
    smoke_base = read(smoke/'io/hybrid.json')
    smoke_final = read(smoke/'io/consensus.json')
    smoke_inputs = []
    for row in smoke_base['records']:
        name = Path(row['input_path']).name
        assert sha(smoke/'audio'/name) == row['input_sha256']
        smoke_inputs.append({'id': Path(name).stem, 'file': name, 'audio_sha256': row['input_sha256'],
                             'pcm_sha256': row['pcm_sha256'], 'duration_sec': row['duration_sec']})
    save(out/'smoke-inputs.json', smoke_inputs)
    save(out/'scoring/parity.json', {'hybrid': smoke_base, 'consensus': smoke_final})
    driver = work/'scripts/run_checkpointed_asr_v13.py'
    target = out/'frozen/scripts'/driver.name
    target.parent.mkdir(parents=True)
    shutil.copyfile(driver, target)
    # Scoring uses a frozen copy of the existing metric implementation and its imports.
    for path in (work/'src/north55_speech').rglob('*.py'):
        destination = out/'frozen'/path.relative_to(work)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    v9 = work/'reports/cockpit-candidates-v10/local-runtime'
    v11 = work/'reports/cockpit-consensus-v11/local-runtime'
    plan = {'count': len(inputs), 'seconds': sum(i['duration_sec'] for i in inputs),
            'speakers': sorted({i['speaker'] for i in inputs}),
            'input_hashes': {name: sha(out/name) for name in ['inputs.json', 'smoke-inputs.json']},
            'reference_sha256': sha(out/'scoring/references.json'),
            'cached_sha256': sha(out/'scoring/cached.json'), 'historical_predictions': evidence,
            'parity_sha256': sha(out/'scoring/parity.json'),
            'driver_sha256': sha(target),
            'metric_sha256': sha(out/'frozen/src/north55_speech/metrics.py'),
            'runtime_sha256': {'hybrid': sha(v9/'runtime.json'), 'consensus': sha(v11/'runtime.json')},
            'entrypoint_sha256': {'hybrid': sha(v9/'frozen/scripts/transcribe_cockpit_hybrid_v10.py'),
                                  'consensus': sha(v11/'frozen/scripts/transcribe_cockpit_consensus_v11.py')},
            'old_plan_sha256': sha(old_plan_path), 'primary_metric': 'lexical_normalizer_v1 corpus WER',
            'secondary_metric': 'canonical_normalizer_v1 symmetric number normalization',
            'all_inputs_included': True, 'local_training': False, 'threshold_tuning': False,
            'source_partition': 'published ATCOSIM test, already used locally as development corpus',
            'sealed_cockpit_test_accessed': False,
            'claim': 'simulated controller speech, four speakers; separate from cockpit evaluation'}
    save(out/'plan.json', plan)
    print(json.dumps({'frozen_inputs': len(inputs), 'historical_predictions': 3802, 'parity_inputs': len(smoke_inputs)}))


if __name__ == '__main__':
    main()
