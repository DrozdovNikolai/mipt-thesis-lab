"""Freeze and run one adaptation of the recovered 221-pair publisher dataset."""

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

from scripts.audit_nus_training_contract import save as atomic_json  # noqa: E402
from scripts.audit_nus_training_contract import sha as file_hash  # noqa: E402

ROOT = REPO / 'reports/publisher-training-v3'
DATA = REPO / 'data/curated/publisher-recovery-v3'
IMAGE = 'north55-speech-train:publisher-v2'
VOLUME = 'north55-speech_publisher_training_v3'


def read(path):
    return json.loads(path.read_bytes())


def freeze():
    if not Path('/.dockerenv').exists():
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
            '-v', REPO.as_posix() + ':/app', '-w', '/app', '-e', 'PYTHONPATH=/app:/app/src',
            IMAGE, '-m', 'scripts.run_publisher_training_v3', 'freeze'], check=True)
        return
    from north55_speech.datasets import load_manifest
    from north55_speech.lora import validate_references

    if (ROOT / 'plan.json').exists() or (ROOT / 'frozen').exists():
        raise ValueError('Preserve the existing experiment')
    config = {'reference_policy': 'publisher_template_recovery_v3', 'quality_evidence': False,
              'selection_allowed': False, 'max_steps': 240}
    train, dev = (load_manifest(DATA / (name + '.jsonl')) for name in ('train', 'dev'))
    validate_references(train, dev, config)
    if len(train) != 221 or len(dev) != 35:
        raise ValueError('Require the complete recovered population and unchanged weak dev')
    prior = REPO / 'reports/nus-lora-ablation-v1'
    previous = read(prior / 'build-plan.json')
    if file_hash(prior / 'inputs.json') != previous['inputs_sha256']:
        raise ValueError('Historical control population changed')
    controls = read(prior / 'inputs.json')['control']
    if len(controls) != 159:
        raise ValueError('Historical control population incomplete')
    if {s.audio_sha256 for s in train} & {i['audio_sha256'] for i in controls}:
        raise ValueError('Training waveform overlaps control')
    references_path = prior / 'scoring/references.json'
    if file_hash(references_path) != previous['scoring_sha256']['references.json']:
        raise ValueError('Historical references changed')
    references = read(references_path)
    items = list(controls)
    for cohort, prefix, samples in [('training_fit', 'fit-', train), ('publisher_weak_dev', 'weak-', dev)]:
        for sample in samples:
            identity = prefix + sample.sample_id
            items.append({'id': identity, 'reference_id': identity, 'cohort': cohort,
                'audio_path': sample.audio_path, 'audio_sha256': sample.audio_sha256,
                'duration_sec': sample.duration_sec, 'channel': sample.channel,
                'input_language': sample.input_language if cohort == 'publisher_weak_dev' else 'en',
                'gain_db': 0., 'group_id': sample.group_id, 'recording_id': sample.recording_id,
                'speaker_ids': sample.speaker_ids})
            references[identity] = sample.reference_text
    if len({i['id'] for i in items}) != len(items):
        raise ValueError('Duplicate evaluation ids')
    atomic_json(ROOT / 'inputs.json', items)
    atomic_json(ROOT / 'scoring/references.json', {i['reference_id']: references[i['reference_id']] for i in items})
    frozen = ROOT / 'frozen'
    for folder in ('src', 'scripts', 'tests', 'configs'):
        shutil.copytree(REPO / folder, frozen / folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('pyproject.toml', 'uv.lock', 'SPEC.md', 'ACCEPTANCE.yaml'):
        shutil.copyfile(REPO / name, frozen / name)
    hashes = {p.relative_to(frozen).as_posix(): file_hash(p) for p in sorted(frozen.rglob('*')) if p.is_file()}
    atomic_json(ROOT / 'frozen-files.json', hashes)
    training = read(REPO / 'reports/nus-training-v1/training.json')
    plan = {'frozen_at': datetime.now(UTC).isoformat(), 'protocol_sha256': file_hash(ROOT / 'protocol.md'),
        'implementation_sha256': hashes, 'inputs_sha256': file_hash(ROOT / 'inputs.json'),
        'references_sha256': file_hash(ROOT / 'scoring/references.json'),
        'train_sha256': file_hash(DATA / 'train.jsonl'), 'dev_sha256': file_hash(DATA / 'dev.jsonl'),
        'source_recovery_plan_sha256': file_hash(REPO / 'reports/publisher-recovery-v3/inference/plan.json'),
        'selected_ids': [s.sample_id for s in train], 'admission': config,
        'base_manifest': training['base_manifest'], 'baseline_model': previous['models']['parent'],
        'config': previous['configs']['parent_on'], 'model_name': 'whisper-small-publisher-recovery-v3-ct2',
        'training': {'updates': 240, 'accumulation': 4, 'learning_rate': 2e-5,
            'kl_weight': 1.0, 'temperature': 2.0, 'rank': 8, 'alpha': 16, 'dropout': .05,
            'seed': 55, 'precision': 'bfloat16', 'encoder_frozen': True},
        'cohorts': dict(Counter(i['cohort'] for i in items)),
        'budget': {'training_runs': 1, 'GPU_ASR': 2*len(items), 'CPU_ASR': 2},
        'quality_evidence': False, 'selection_allowed': False, 'test_accessed': False,
        'release_promoted': False, 'checkpoint_selection': 'fixed_final_240_updates'}
    atomic_json(ROOT / 'plan.json', plan)
    print(json.dumps({'train': len(train), 'minutes': sum(s.duration_sec for s in train)/60,
                      'cohorts': plan['cohorts'], 'budget': plan['budget']}, indent=2))


def run(stage):
    plan = read(ROOT / 'plan.json')
    if file_hash(ROOT / 'protocol.md') != plan['protocol_sha256']:
        raise ValueError('Protocol changed')
    for name, expected in plan['implementation_sha256'].items():
        if file_hash(ROOT / 'frozen' / name) != expected:
            raise ValueError('Frozen implementation changed: ' + name)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ').lower()
    name = 'north55-publisher-training-v3-' + stage + '-' + stamp
    cmd = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
        '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1', '-e', 'CUDA_VISIBLE_DEVICES=0',
        '-e', 'PYTHONPATH=/app:/app/src', '-w', '/app',
        '-e', 'LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib']
    if stage in ('train', 'convert', 'baseline', 'candidate'):
        cmd += ['--gpus', 'device=0']

    def mount(local, remote, ro=True):
        cmd.extend(['-v', str(local).replace('\\', '/') + ':' + remote + (':ro' if ro else '')])

    mount(ROOT / 'frozen', '/app')
    mount('north55-speech_model_cache', '/models')
    mount('north55-speech_audio_data', '/audio')
    mount(VOLUME, '/experiment', stage not in ('init', 'train', 'convert'))
    if stage in ('score', 'tests'):
        mount(ROOT, '/study', False)
    else:
        for filename in ('plan.json', 'inputs.json'):
            mount(ROOT / filename, '/study/' + filename)
        out = ROOT / ('io-' + stage)
        out.mkdir(exist_ok=True)
        mount(out, '/output', False)
        if stage == 'train':
            mount(DATA / 'train.jsonl', '/train/train.jsonl')
        if stage == 'convert':
            mount(ROOT / 'training.json', '/study/training.json')
        if stage in ('candidate', 'cpu'):
            mount(ROOT / 'conversion.json', '/study/conversion.json')
    if stage == 'init':
        cmd += ['--user', '0:0', IMAGE, '-c',
            "from pathlib import Path; import os; p=Path('/experiment').resolve(); "
            "assert str(p)=='/experiment' and not any(p.iterdir()); os.chown(p,10001,10001)"]
    elif stage == 'tests':
        cmd += [IMAGE, '-m', 'pytest', '-q', 'tests/test_publisher_training_v3.py',
                'tests/test_retention.py', 'tests/test_publisher_recovery_v3.py',
                '--junitxml=/study/test-results.xml']
    else:
        cmd += [IMAGE, '-u', '-m', 'scripts.publisher_training_v3', stage]
    print('Starting', name, flush=True)
    result = subprocess.run(cmd, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    atomic_json(ROOT / (name + '.json'), {'name': name, 'image': obj['Image'], 'state': obj['State'],
        'network': obj['HostConfig']['NetworkMode'], 'command': obj['Config']['Cmd'], 'mounts': obj['Mounts'],
        'devices': obj['HostConfig']['DeviceRequests']})
    (ROOT / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)
    if stage in ('train', 'convert'):
        filename = 'training.json' if stage == 'train' else 'conversion.json'
        with (ROOT / filename).open('xb') as stream:
            stream.write((ROOT / ('io-' + stage) / filename).read_bytes())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'init', 'tests', 'train', 'convert', 'baseline', 'candidate', 'cpu', 'score'])
    args = parser.parse_args()
    freeze() if args.stage == 'freeze' else run(args.stage)
