"""PowerShell/Linux launcher: freeze, trace, fit, context, cpu, score."""

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/nus-diagnosis-v1'
PRIOR = REPO / 'reports/nus-training-v1/evaluation-v2'
IMAGE = 'north55-speech-train:publisher-v2'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def freeze():
    if (ROOT / 'plan.json').exists() or (ROOT / 'frozen').exists():
        raise ValueError('Preserve existing frozen study')
    ROOT.mkdir(parents=True, exist_ok=True)
    old = read(PRIOR / 'plan.json')
    previous_inputs = PRIOR / 'inputs.json'
    train = REPO / 'data/curated/nus-training-v1/train.jsonl'
    if sha(previous_inputs) != old['inputs_sha256']:
        raise ValueError('Prior evaluation inputs changed')
    if sha(train) != read(REPO / 'reports/nus-training-v1/plan.json')['train_sha256']:
        raise ValueError('Frozen training manifest changed')
    samples = [json.loads(line) for line in train.read_text(encoding='utf-8').splitlines()]
    selected = sorted((s for s in samples if s['source_dataset'] == 'NUS-SIA/CDE4301-VR-401'), key=lambda s: s['sample_id'])
    if len(selected) != 275 or any(s['split'] != 'train' or s['transcript_status'] != 'weak' for s in selected):
        raise ValueError('Unexpected fitting population')
    fit = [{'id': s['sample_id'], 'audio_path': s['audio_path'], 'audio_sha256': s['audio_sha256'],
            'duration_sec': s['duration_sec'], 'input_language': s['input_language'], 'gain_db': 0.,
            'group_id': s['group_id'], 'cohort': 'nus_training_fit', 'reference_id': s['sample_id']} for s in selected]
    items = read(previous_inputs)
    trace = [i for i in items if i['cohort'] in ('partial_human_dev', 'quiet_partial_human_dev')]
    if len(trace) != 10:
        raise ValueError('Expected all five reviewed utterances and their quiet copies')
    save(ROOT / 'inputs.json', {'trace': trace, 'fit': fit, 'context': items})
    # References and historical predictions are only mounted by the scoring stage.
    refs_path = REPO / 'data/curated/language-large-v1/scoring/references.json'
    if sha(refs_path) != old['references_sha256']:
        raise ValueError('Frozen development references changed')
    save(ROOT / 'scoring/fit-references.json', {s['sample_id']: s['reference_text'] for s in selected})
    save(ROOT / 'scoring/dev-references.json', read(refs_path))
    parent_path = PRIOR / 'historical/parent.json'
    if sha(parent_path) != old['historical_sha256']['parent']:
        raise ValueError('Historical parent answers changed')
    save(ROOT / 'scoring/parent.json', read(parent_path))
    execution = read(PRIOR / 'nus/execution.json')
    if execution['plan_sha256'] != sha(PRIOR / 'plan.json'):
        raise ValueError('Prior candidate execution changed')
    records = {}
    for item in items:
        path = PRIOR / 'nus/predictions' / (item['id'] + '.json')
        if sha(path) != execution['prediction_sha256'][path.name]:
            raise ValueError('Prior candidate response changed')
        records[item['id']] = read(path)
    save(ROOT / 'scoring/nus.json', records)
    source = ROOT / 'frozen'
    for directory in ('src', 'scripts', 'configs', 'tests'):
        shutil.copytree(REPO / directory, source / directory,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / filename, source / filename)
    hashes = {p.relative_to(source).as_posix(): sha(p) for p in sorted(source.rglob('*')) if p.is_file()}
    save(ROOT / 'frozen-files.json', hashes)
    configs = {s + '_' + context: old['configs'][s] | {'condition_on_previous_text': context == 'on'}
               for s in ('parent', 'nus') for context in ('on', 'off')}
    save(ROOT / 'plan.json', {'frozen_at': datetime.now(UTC).isoformat(), 'models': {s: old['models'][s] for s in ('parent', 'nus')},
         'configs': configs, 'inputs_sha256': sha(ROOT / 'inputs.json'), 'protocol_sha256': sha(ROOT / 'protocol.md'),
         'implementation_sha256': {k: v for k, v in hashes.items() if k.startswith(('src/', 'scripts/')) or
                                   k in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml', 'uv.lock')},
         'scoring_sha256': {p.name: sha(p) for p in (ROOT / 'scoring').glob('*.json')},
         'previous_plan_sha256': sha(PRIOR / 'plan.json'), 'train_manifest_sha256': sha(train),
         'fit_inputs': len(fit), 'trace_inputs': len(trace), 'context_inputs': len(items),
         'new_weights': 0, 'new_decoder_configurations': 2, 'test_accessed': False, 'release_promoted': False,
         'quality_evidence': False, 'scope': 'Diagnostic extension; no candidate selection under the exhausted original search budget.'})
    print('Frozen: 275 train fitting pairs; 10 traced dev/quiet inputs; 675 exposed controls; no training or test.')


def run(stage, system):
    frozen = ROOT / 'frozen'
    for name, expected in read(ROOT / 'frozen-files.json').items():
        if sha(frozen / name) != expected:
            raise ValueError('Frozen file changed: ' + name)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'north55-nus-diagnosis-{stage}-{system or "all"}-{stamp}'.lower()
    args = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
            '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1',
            '-e', 'LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib']
    if stage in ('trace', 'fit', 'context'):
        args += ['--gpus', 'all']

    def mount(local, remote, ro=True):
        args.extend(['-v', str(local).replace('\\', '/') + ':' + remote + (':ro' if ro else '')])

    for directory in ('src', 'scripts', 'configs', 'tests'):
        mount(frozen / directory, '/app/' + directory)
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock'):
        mount(frozen / filename, '/app/' + filename)
    mount('north55-speech_audio_data', '/audio')
    mount('north55-speech_model_cache', '/models')
    if stage == 'score':
        mount(ROOT, '/study', False)
        args += [IMAGE, '-u', '-m', 'scripts.score_nus_failure_diagnosis']
    elif stage == 'tests':
        mount(ROOT / 'tests', '/results', False)
        args += [IMAGE, '-m', 'pytest', 'tests/test_nus_failure_diagnosis.py', '-q', '--junitxml=/results/results.xml']
    else:
        for filename in ('plan.json', 'inputs.json', 'protocol.md'):
            mount(ROOT / filename, '/study/' + filename)
        effective_stage = 'trace' if stage == 'cpu' else stage
        output = ('cpu-' if stage == 'cpu' else '') + effective_stage + '-' + system
        (ROOT / output).mkdir(exist_ok=True)
        mount(ROOT / output, '/study/' + output, False)
        args += [IMAGE, '-u', '-m', 'scripts.nus_failure_diagnosis', effective_stage, system]
        if stage == 'cpu':
            args += ['--cpu']
    print('Starting ' + name, flush=True)
    result = subprocess.run(args, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(ROOT / (name + '.json'), {'name': name, 'image_id': obj['Image'], 'network_mode': obj['HostConfig']['NetworkMode'],
         'state': obj['State'], 'command': obj['Config']['Cmd'], 'mounts': [{k: m[k] for k in ('Type', 'Source', 'Destination', 'RW')} for m in obj['Mounts']]})
    (ROOT / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'trace', 'fit', 'context', 'cpu', 'tests', 'score'))
    parser.add_argument('system', nargs='?', choices=('parent_on', 'parent_off', 'nus_on', 'nus_off'))
    args = parser.parse_args()
    if args.stage in ('trace', 'fit', 'context', 'cpu') and args.system is None:
        parser.error('system is required for inference')
    freeze() if args.stage == 'freeze' else run(args.stage, args.system)
