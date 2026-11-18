"""Prepare, freeze and execute the isolated robust cockpit experiment."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from scripts.audit_nus_training_contract import read, save, sha

REPO = Path(__file__).resolve().parents[1]
IN_DOCKER = Path('/.dockerenv').exists()
ROOT = Path('/study') if IN_DOCKER else REPO/'reports/cockpit-robust-v5'
DATA = REPO/'data/curated/cockpit-hard-v4'
IMAGE = 'north55-speech-train:publisher-v2'
VOLUME = 'north55-speech_cockpit_robust_v5'
ARMS = ('uniform', 'balanced', 'balanced-silence')


def freeze():
    if not IN_DOCKER:
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python',
            '-v', REPO.as_posix()+':/app:ro', '-v', ROOT.as_posix()+':/study',
            '-v', VOLUME+':/experiment', '-v', 'north55-speech_audio_data:/audio:ro',
            '-w', '/app', '-e', 'PYTHONPATH=/app:/app/src', IMAGE,
            '-m', 'scripts.run_cockpit_robust_v5', 'freeze'], check=True)
        return
    import soundfile as sf

    from north55_speech.datasets import load_manifest
    from north55_speech.hard_adaptation import validate_population
    from north55_speech.robust_adaptation import (
        TRAINING,
        augment_waveform,
        negative_waveform,
        schedules,
    )
    from scripts.cockpit_robust_v5 import pcm
    from scripts.decoding_diagnostics import load_audio

    if (ROOT/'plan.json').exists() or (ROOT/'frozen').exists():
        raise ValueError('Preserve prior frozen study')
    train, dev = (load_manifest(DATA/(s+'.jsonl')) for s in ('train', 'dev'))
    validate_population(train, dev)
    prior = REPO/'reports/cockpit-training-v4'
    old = read(prior/'plan.json')
    if sha(DATA/'train.jsonl') != old['train_sha256'] or sha(DATA/'dev.jsonl') != old['dev_sha256']:
        raise ValueError('Prior data changed')
    if sha(prior/'inputs.json') != old['inputs_sha256'] or sha(prior/'scoring/references.json') != old['references_sha256']:
        raise ValueError('Prior controls changed')
    inputs, refs = read(prior/'inputs.json'), read(prior/'scoring/references.json')
    if len(inputs) != 441:
        raise ValueError('Prior population changed')
    cockpit = [i for i in inputs if i['cohort'] in ('partial_human_dev', 'publisher_weak_dev')]
    if len(cockpit) != 40:
        raise ValueError('Unexpected cockpit dev size')
    directory = Path('/experiment/eval-audio')
    if directory.exists():
        raise ValueError('Preserve prepared evaluation audio')
    directory.mkdir()
    audit = []

    def add(identity, x, reference, cohort, group, language, metadata):
        path = directory/(identity+'.wav')
        sf.write(path, x, 16000, subtype='FLOAT')
        inputs.append({'id': identity, 'reference_id': identity, 'cohort': cohort,
            'audio_path': 'eval-audio/'+path.name, 'audio_sha256': sha(path),
            'effective_waveform_sha256': pcm(x), 'duration_sec': len(x)/16000,
            'channel': 0, 'input_language': language, 'gain_db': 0., 'group_id': group, 'synthetic_v5': True})
        refs[identity] = reference
        audit.append({'id': identity, 'audio_sha256': sha(path), **metadata})

    for index, item in enumerate(cockpit):
        source = load_audio(item)
        for j, snr in enumerate((15, 5)):
            seed = 750000+2*index+j
            x, meta = augment_waveform(source, seed, snr)
            add(f'acoustic-{snr}-'+item['id'], x, refs[item['reference_id']],
                f'acoustic_{snr}_'+item['cohort'], item['group_id'], item['input_language'],
                meta | {'parent_id': item['id'], 'parent_pcm_sha256': pcm(source), 'text_unchanged': True})
    for index in range(20):
        x, meta = negative_waveform(850000+index, index)
        add('synthetic-empty-'+str(index), x, '', 'synthetic_nonspeech', 'synthetic-family-'+meta['family'], 'auto', meta)
    assert len(inputs) == 541 and len({i['id'] for i in inputs}) == 541
    schedule = schedules(train)
    save(ROOT/'schedule.json', schedule)
    save(ROOT/'inputs.json', inputs)
    save(ROOT/'scoring/references.json', refs)
    save(ROOT/'synthetic-evaluation-audit.json', audit)
    frozen = ROOT/'frozen'
    for folder in ('src', 'scripts', 'tests', 'configs'):
        shutil.copytree(REPO/folder, frozen/folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('pyproject.toml', 'uv.lock', 'SPEC.md', 'ACCEPTANCE.yaml'):
        shutil.copyfile(REPO/name, frozen/name)
    hashes = {p.relative_to(frozen).as_posix(): sha(p) for p in sorted(frozen.rglob('*')) if p.is_file()}
    save(ROOT/'frozen-files.json', hashes)
    plan = {'frozen_at': datetime.now(UTC).isoformat(), 'protocol_sha256': sha(ROOT/'protocol.md'),
        'implementation_sha256': hashes, 'schedule_sha256': sha(ROOT/'schedule.json'),
        'inputs_sha256': sha(ROOT/'inputs.json'), 'references_sha256': sha(ROOT/'scoring/references.json'),
        'train_sha256': sha(DATA/'train.jsonl'), 'dev_sha256': sha(DATA/'dev.jsonl'),
        'selected_ids': [s.sample_id for s in train], 'train_rows': len(train), 'training': TRAINING,
        'base_manifest': old['base_manifest'], 'baseline_model': old['baseline_model'], 'config': old['config'],
        'model_names': {a: 'whisper-small-cockpit-robust-v5-'+a for a in ARMS},
        'cohorts': dict(Counter(i['cohort'] for i in inputs)), 'prior_plan_sha256': sha(prior/'plan.json'),
        'budget': {'runs': 3, 'actual_updates_each': 240, 'new_GPU_ASR': 1723, 'reused_baseline_ASR': 441, 'CPU_ASR': 6},
        'quality_evidence': False, 'selection_allowed': False, 'release_promoted': False,
        'test_accessed': False, 'blind_dev_accessed': False}
    save(ROOT/'plan.json', plan)
    print(json.dumps({'cohorts': plan['cohorts'], 'budget': plan['budget'], 'scheduled_variants': 420}, indent=2), flush=True)


def launch(stage, arm):
    if stage != 'init':
        plan = read(ROOT/'plan.json')
        if sha(ROOT/'protocol.md') != plan['protocol_sha256']:
            raise ValueError('Protocol changed')
        for name, value in plan['implementation_sha256'].items():
            if sha(ROOT/'frozen'/name) != value:
                raise ValueError('Frozen implementation changed')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ').lower()
    label = arm if stage == 'candidate' else stage+'-'+arm if stage == 'cpu' else stage
    name = 'north55-cockpit-robust-v5-'+label+'-'+stamp
    cmd = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
        '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1', '-e', 'CUDA_VISIBLE_DEVICES=0',
        '-e', 'PYTHONPATH=/app:/app/src', '-w', '/app',
        '-e', 'LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib']
    if stage in ('train', 'convert', 'baseline', 'candidate'):
        cmd += ['--gpus', 'device=0']

    def mount(path, target, ro=True):
        cmd.extend(['-v', str(path).replace('\\', '/')+':'+target+(':ro' if ro else '')])
    mount(ROOT/'frozen' if stage != 'init' else REPO, '/app')
    mount(VOLUME, '/experiment', stage not in ('init', 'train', 'convert'))
    mount('north55-speech_audio_data', '/audio')
    mount('north55-speech_model_cache', '/models')
    if stage == 'init':
        cmd += ['--user', '0:0', IMAGE, '-c', "from pathlib import Path; import os; p=Path('/experiment'); assert not any(p.iterdir()); os.chown(p,10001,10001)"]
    elif stage in ('tests', 'score', 'audit'):
        mount(ROOT, '/study', False)
        if stage == 'tests':
            cmd += [IMAGE, '-m', 'pytest', '-q', '-o', 'cache_dir=/tmp/robust-tests',
                'tests/test_robust_adaptation.py', 'tests/test_hard_adaptation.py', 'tests/test_publisher_training_v3.py',
                '--junitxml=/study/test-results.xml']
        else:
            cmd += [IMAGE, '-m', 'scripts.report_cockpit_robust_v5', stage]
    else:
        for filename in ('plan.json', 'inputs.json', 'schedule.json'):
            mount(ROOT/filename, '/study/'+filename)
        output = ROOT/('io-'+label)
        output.mkdir(exist_ok=True)
        mount(output, '/output', False)
        if stage == 'train':
            for split in ('train', 'dev'):
                mount(DATA/(split+'.jsonl'), '/train/'+split+'.jsonl')
        if stage == 'convert':
            mount(ROOT/'training.json', '/study/training.json')
        if stage in ('candidate', 'cpu'):
            mount(ROOT/'io-convert/conversions'/(arm+'.json'), '/study/conversion.json')
        if stage == 'baseline':
            mount(REPO/'reports/cockpit-training-v4', '/prior')
        cmd += [IMAGE, '-u', '-m', 'scripts.cockpit_robust_v5', stage]
    print('Starting', name, flush=True)
    result = subprocess.run(cmd, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(ROOT/(name+'.json'), {'name': name, 'image': obj['Image'], 'state': obj['State'],
        'network': obj['HostConfig']['NetworkMode'], 'command': obj['Config']['Cmd'], 'mounts': obj['Mounts'],
        'devices': obj['HostConfig']['DeviceRequests']})
    (ROOT/(name+'.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)
    if stage in ('train', 'convert'):
        filename = 'training.json' if stage == 'train' else 'conversion.json'
        with (ROOT/filename).open('xb') as stream:
            stream.write((ROOT/('io-'+stage)/filename).read_bytes())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['init', 'freeze', 'tests', 'train', 'convert', 'baseline', 'candidate', 'cpu', 'vad', 'score', 'audit'])
    p.add_argument('arm', nargs='?', choices=ARMS)
    a = p.parse_args()
    if a.stage in ('candidate', 'cpu') and a.arm is None:
        p.error('arm is required')
    freeze() if a.stage == 'freeze' else launch(a.stage, a.arm)
