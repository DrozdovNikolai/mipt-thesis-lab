"""Freeze and execute the fresh NUS decoder-only experiment on PowerShell/Linux."""

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime

from scripts import run_nus_convergence as launch
from scripts.audit_nus_training_contract import read, save, sha

REPO = launch.REPO
ROOT = REPO / 'reports/nus-decoder-v1'
SOURCE = REPO / 'reports/nus-lora-ablation-v1'
launch.ROOT = ROOT
launch.VOLUME = 'north55-speech_nus_decoder_v1'
launch.WORKER = 'scripts.nus_decoder'
launch.TEST_FILE = 'tests/test_decoder_adaptation.py'
launch.TRAIN_MANIFEST = REPO / 'data/curated/nus-training-v1/train.jsonl'


def freeze():
    if (ROOT / 'plan.json').exists() or (ROOT / 'frozen').exists():
        raise ValueError('Preserve existing experiment')
    previous = read(SOURCE / 'build-plan.json')
    original = REPO / 'reports/nus-training-v1'
    old_training, old_plan = read(original / 'training.json'), read(original / 'plan.json')
    if sha(launch.TRAIN_MANIFEST) != old_training['train_sha256'] or old_plan['train_sha256'] != old_training['train_sha256']:
        raise ValueError('Original full training set changed')
    rows = [json.loads(line) for line in launch.TRAIN_MANIFEST.read_text(encoding='utf-8').splitlines()]
    if len(rows) != 675 or len({r['sample_id'] for r in rows}) != 675 or any(r['split'] != 'train' for r in rows):
        raise ValueError('Require exactly the original 675 unique training rows')
    if sha(original / 'permission.json') != old_plan['permission_sha256']:
        raise ValueError('Source permission evidence changed')
    if sha(SOURCE / 'inputs.json') != previous['inputs_sha256']:
        raise ValueError('Historical evaluation population changed')
    source_inputs = read(SOURCE / 'inputs.json')
    fit, control = source_inputs['fit'], source_inputs['control']
    if len(fit) != 275 or len(control) != 159:
        raise ValueError('Unexpected diagnostic population')
    train_by_id = {r['sample_id']: r for r in rows}
    if any(i['id'] not in train_by_id or i['audio_sha256'] != train_by_id[i['id']]['audio_sha256'] for i in fit):
        raise ValueError('NUS fitting population differs from training')
    if {r['audio_sha256'] for r in rows} & {i['audio_sha256'] for i in control}:
        raise ValueError('Control waveform overlaps training')
    train_speakers = {s for r in rows for s in r['speaker_ids']}
    if train_speakers & {i['speaker_id'] for i in control if i.get('speaker_id')}:
        raise ValueError('Known training speaker overlaps diagnostic control')
    for old_name, new_name in [('parent_on.json', 'parent.json'), ('nus_on.json', 'joint.json'), ('references.json', 'references.json')]:
        if sha(SOURCE / 'scoring' / old_name) != previous['scoring_sha256'][old_name]:
            raise ValueError('Historical references/predictions changed')
        save(ROOT / 'scoring' / new_name, read(SOURCE / 'scoring' / old_name))
    save(ROOT / 'inputs.json', {'fit': fit, 'transfer': control,
        'cpu': [fit[0], next(i for i in control if i['cohort'] == 'general_ru')]})
    frozen = ROOT / 'frozen'
    for directory in ('src', 'scripts', 'configs', 'tests'):
        shutil.copytree(REPO / directory, frozen / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / filename, frozen / filename)
    hashes = {p.relative_to(frozen).as_posix(): sha(p) for p in sorted(frozen.rglob('*')) if p.is_file()}
    save(ROOT / 'frozen-files.json', hashes)
    plan = {'frozen_at': datetime.now(UTC).isoformat(), 'protocol_sha256': sha(ROOT / 'protocol.md'),
        'implementation_sha256': {k: v for k, v in hashes.items() if k.startswith(('src/', 'scripts/')) or
            k in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml', 'uv.lock')},
        'inputs_sha256': sha(ROOT / 'inputs.json'), 'subset_sha256': sha(launch.TRAIN_MANIFEST),
        'train_manifest_kind': 'complete_original_675_rows_not_a_subset', 'selected_ids': [r['sample_id'] for r in rows],
        'base_manifest': old_training['base_manifest'], 'permission_evidence_sha256': old_plan['permission_sha256'],
        'source_training_sha256': sha(original / 'training.json'), 'source_plan_sha256': sha(original / 'plan.json'),
        'historical_scoring_plan_sha256': sha(SOURCE / 'build-plan.json'), 'data': old_plan['data'],
        'parent_model': previous['models']['parent'], 'joint_model': previous['models']['nus'],
        'config': previous['configs']['parent_on'], 'cpu_inputs': True,
        'scoring_sha256': {p.name: sha(p) for p in (ROOT / 'scoring').iterdir()},
        'model_names': {str(s): f'whisper-small-nus-decoder-v1-step{s}' for s in (240, 1200)},
        'decoder_training': {'max_steps': 1200, 'milestones': [240, 1200], 'initial_lr': 5e-5,
            'continuation_lr': 2e-5, 'schedule': 'linear_first_240_then_constant',
            'rank': 8, 'alpha': 16, 'dropout': .05, 'seed': 55, 'train_rows': 675,
            'from_original_base': True, 'encoder_frozen': True},
        'budget': {'new_training_arms': 1, 'optimizer_steps': 1200, 'fit_ASR': 550, 'control_ASR': 318, 'CPU_ASR': 4},
        'quality_evidence': False, 'selection_allowed': False, 'test_accessed': False, 'release_promoted': False}
    from north55_speech.decoder_adaptation import validate_decoder_plan
    validate_decoder_plan(plan)
    save(ROOT / 'plan.json', plan)
    print('Frozen fresh decoder-only adaptation: 675 pairs, 1200 steps, 868 GPU + 4 CPU ASR calls.', flush=True)


def initialize():
    name = 'north55-nus-decoder-volume-init-v1'
    subprocess.run(['docker', 'run', '--name', name, '--network', 'none', '--user', '0:0',
        '-v', launch.VOLUME + ':/experiment', '--entrypoint', 'python', launch.IMAGE, '-c',
        "from pathlib import Path; import os; p=Path('/experiment').resolve(); "
        "assert str(p)=='/experiment' and not any(p.iterdir()), 'Only initialize the empty experiment volume'; "
        "os.chown(p,10001,10001); print('Initialized empty decoder experiment volume')"], check=True)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(ROOT / 'volume-initialization.json', {'image': obj['Image'], 'state': obj['State'],
        'network': obj['HostConfig']['NetworkMode'], 'mounts': obj['Mounts']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'init', 'tests', 'train', 'convert', 'fit', 'transfer', 'cpu', 'score-transfer'])
    parser.add_argument('step', nargs='?', type=int, choices=[240, 1200])
    args = parser.parse_args()
    if args.stage in ('fit', 'transfer', 'cpu') and args.step is None:
        parser.error('step is required')
    if args.stage == 'freeze':
        freeze()
    elif args.stage == 'init':
        initialize()
    else:
        launch.run(args.stage, args.step)
