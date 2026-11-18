"""Freeze and launch three matched hard/noisy aviation adaptation regimes."""

import argparse
import json
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from scripts.audit_nus_training_contract import read, save, sha

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/cockpit-training-v4'
DATA = REPO / 'data/curated/cockpit-hard-v4'
IMAGE = 'north55-speech-train:publisher-v2'
VOLUME = 'north55-speech_cockpit_training_v4'
ARM_NAMES = ('decoder-kl', 'decoder-ce', 'full-ce')


def freeze():
    if not Path('/.dockerenv').exists():
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
            '-v', REPO.as_posix() + ':/app', '-v', 'north55-speech_audio_data:/audio', '-w', '/app',
            '-e', 'PYTHONPATH=/app:/app/src', IMAGE, '-m', 'scripts.run_cockpit_training_v4', 'freeze'], check=True)
        return
    import numpy as np
    import soundfile as sf
    from scipy.signal import coherence

    from north55_speech.core import settings
    from north55_speech.datasets import load_manifest
    from north55_speech.hard_adaptation import TRAINING, validate_population
    from scripts.cockpit_hard_v4 import clipped

    if (ROOT / 'plan.json').exists() or (ROOT / 'frozen').exists():
        raise ValueError('Preserve the existing experiment')
    train, dev = (load_manifest(DATA / (s + '.jsonl')) for s in ('train', 'dev'))
    validate_population(train, dev)
    data_result = read(REPO / 'reports/cockpit-hard-v4/result.json')
    if sha(DATA / 'train.jsonl') != data_result['train_sha256'] or not data_result['accepted_hard'] or not data_result['noisy_pairs']:
        raise ValueError('Require actual new hard and noisy training pairs')
    prior = REPO / 'reports/publisher-training-v3'
    previous = read(prior / 'plan.json')
    if sha(prior / 'inputs.json') != previous['inputs_sha256'] or sha(prior / 'scoring/references.json') != previous['references_sha256']:
        raise ValueError('Historical diagnostic population changed')
    items = [i for i in read(prior / 'inputs.json') if i['cohort'] != 'training_fit']
    old_references = read(prior / 'scoring/references.json')
    refs = {i['reference_id']: old_references[i['reference_id']] for i in items}
    if len(items) != 194 or {s.audio_sha256 for s in train} & {i['audio_sha256'] for i in items}:
        raise ValueError('Control population incomplete or overlapping training')
    # Paired noisy development check uses the unchanged weak text of the clean clip.
    raw_dev = load_manifest(REPO / 'data/curated/bleriot-v2/manifests/train-dev/dev.jsonl')
    variants = {s.variant_of: s for s in raw_dev if s.variant_of
        and (s.augmentation or {}).get('parent_link_status') == 'ACOUSTICALLY_CONFIRMED'}
    noise_audit = []
    for row in dev:
        p = row.annotation_provenance
        parent = variants.get(p['source_sample_id'])
        if parent is None:
            continue
        identity_id = 'dev-noisy-' + row.sample_id
        crop = clipped(parent, identity_id, p['original_start_sec'], p['original_end_sec'], 'cockpit-hard-v4-dev-noisy')
        a, _ = sf.read(settings.audio_root / row.audio_path, dtype='float32')
        b, _ = sf.read(settings.audio_root / crop['audio_path'], dtype='float32')
        n = min(len(a), len(b))
        frequencies, values = coherence(a[:n], b[:n], fs=16000, nperseg=1024, noverlap=512)
        score = float(np.mean(values[(frequencies >= 300) & (frequencies <= 3000)]))
        admitted = bool(np.isfinite(score) and score >= .20 and abs(len(a)-len(b)) <= 2)
        noise_audit.append({'id': identity_id, 'local_coherence': score, 'accepted': admitted,
            'source': parent.sample_id, 'source_sha256': parent.audio_sha256, 'clean_clip': row.sample_id})
        if admitted:
            items.append({'id': identity_id, 'reference_id': identity_id, 'cohort': 'publisher_noisy_weak_dev',
                **{k: crop[k] for k in ('audio_path', 'audio_sha256', 'duration_sec', 'channel')},
                'input_language': row.input_language, 'gain_db': 0., 'group_id': row.group_id})
            refs[identity_id] = row.reference_text
    for row in train:
        method = row.annotation_provenance['method']
        cohort = 'train_noisy_fit' if row.variant_of else ('train_hard_fit' if method == 'cockpit_hard_teacher_consensus_v4' else 'train_retained_fit')
        identity_id = 'fit-' + row.sample_id
        items.append({'id': identity_id, 'reference_id': identity_id, 'cohort': cohort,
            'audio_path': row.audio_path, 'audio_sha256': row.audio_sha256, 'duration_sec': row.duration_sec,
            'channel': row.channel, 'input_language': 'en', 'gain_db': 0., 'group_id': row.group_id})
        refs[identity_id] = row.reference_text
    if len({i['id'] for i in items}) != len(items):
        raise ValueError('Duplicate inference ids')
    save(ROOT / 'inputs.json', items)
    save(ROOT / 'scoring/references.json', refs)
    save(ROOT / 'noisy-dev-audit.json', noise_audit)
    frozen = ROOT / 'frozen'
    for folder in ('src', 'scripts', 'tests', 'configs'):
        shutil.copytree(REPO / folder, frozen / folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('pyproject.toml', 'uv.lock', 'SPEC.md', 'ACCEPTANCE.yaml'):
        shutil.copyfile(REPO / name, frozen / name)
    hashes = {p.relative_to(frozen).as_posix(): sha(p) for p in sorted(frozen.rglob('*')) if p.is_file()}
    save(ROOT / 'frozen-files.json', hashes)
    plan = {'frozen_at': datetime.now(UTC).isoformat(), 'protocol_sha256': sha(ROOT / 'protocol.md'),
        'implementation_sha256': hashes, 'inputs_sha256': sha(ROOT / 'inputs.json'),
        'references_sha256': sha(ROOT / 'scoring/references.json'), 'train_sha256': sha(DATA / 'train.jsonl'),
        'dev_sha256': sha(DATA / 'dev.jsonl'), 'data_result_sha256': sha(REPO / 'reports/cockpit-hard-v4/result.json'),
        'train_rows': len(train), 'selected_ids': [s.sample_id for s in train],
        'base_manifest': previous['base_manifest'], 'baseline_model': previous['baseline_model'],
        'config': previous['config'], 'training': TRAINING,
        'model_names': {a: 'whisper-small-cockpit-hard-v4-' + a for a in ARM_NAMES},
        'cohorts': dict(Counter(i['cohort'] for i in items)),
        'budget': {'training_runs': 3, 'actual_updates_each': 240, 'GPU_ASR': 4*len(items), 'CPU_ASR': 6},
        'blind_review_dev_used': False, 'quality_evidence': False, 'selection_allowed': False,
        'test_accessed': False, 'release_promoted': False}
    save(ROOT / 'plan.json', plan)
    print(json.dumps({'train': len(train), 'cohorts': plan['cohorts'], 'budget': plan['budget']}, indent=2), flush=True)


def run(stage, arm):
    plan = read(ROOT / 'plan.json')
    if sha(ROOT / 'protocol.md') != plan['protocol_sha256']:
        raise ValueError('Protocol changed')
    for name, expected in plan['implementation_sha256'].items():
        if sha(ROOT / 'frozen' / name) != expected:
            raise ValueError('Frozen implementation changed')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ').lower()
    label = arm if stage == 'candidate' else (stage + '-' + arm if stage == 'cpu' else stage)
    name = 'north55-cockpit-training-v4-' + label + '-' + stamp
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
    if stage in ('tests', 'score'):
        mount(ROOT, '/study', False)
    else:
        for filename in ('plan.json', 'inputs.json'):
            mount(ROOT / filename, '/study/' + filename)
        output = ROOT / ('io-' + label)
        output.mkdir(exist_ok=True)
        mount(output, '/output', False)
        if stage == 'train':
            for split in ('train', 'dev'):
                mount(DATA / (split + '.jsonl'), '/train/' + split + '.jsonl')
        if stage == 'convert':
            mount(ROOT / 'training.json', '/study/training.json')
        if stage in ('candidate', 'cpu'):
            mount(ROOT / 'io-convert/conversions' / (arm + '.json'), '/study/conversion.json')
    if stage == 'init':
        cmd += ['--user', '0:0', IMAGE, '-c', "from pathlib import Path; import os; p=Path('/experiment').resolve(); assert str(p)=='/experiment' and not any(p.iterdir()); os.chown(p,10001,10001)"]
    elif stage == 'tests':
        cmd += [IMAGE, '-m', 'pytest', '-q', '-o', 'cache_dir=/tmp/hard-training-tests',
            'tests/test_cockpit_hard_v4.py', 'tests/test_hard_adaptation.py', 'tests/test_retention.py',
            'tests/test_publisher_training_v3.py', '--junitxml=/study/test-results.xml']
    else:
        cmd += [IMAGE, '-u', '-m', 'scripts.cockpit_training_v4', stage]
    print('Starting', name, flush=True)
    result = subprocess.run(cmd, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(ROOT / (name + '.json'), {'name': name, 'image': obj['Image'], 'state': obj['State'],
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
    parser.add_argument('arm', nargs='?', choices=ARM_NAMES)
    args = parser.parse_args()
    if args.stage in ('candidate', 'cpu') and args.arm is None:
        parser.error('arm is required')
    freeze() if args.stage == 'freeze' else run(args.stage, args.arm)
