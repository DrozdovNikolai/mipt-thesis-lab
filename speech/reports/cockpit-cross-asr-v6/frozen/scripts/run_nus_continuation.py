"""Freeze, initialize, execute and replay the separate NUS continuation study."""

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime

from scripts import run_nus_convergence as launch
from scripts.audit_nus_training_contract import read, save, sha

REPO = launch.REPO
PREVIOUS = REPO / 'reports/nus-convergence-v1'
ROOT = REPO / 'reports/nus-continuation-v1'
launch.ROOT = ROOT
launch.VOLUME = 'north55-speech_nus_continuation_v1'
launch.SOURCE_VOLUME = 'north55-speech_nus_convergence_v1'
launch.WORKER = 'scripts.nus_continuation'
launch.TEST_FILE = 'tests/test_continuation.py'


def freeze():
    if (ROOT / 'plan.json').exists() or (ROOT / 'frozen').exists():
        raise ValueError('Preserve the previous freeze')
    old = read(PREVIOUS / 'plan.json')
    summary = read(PREVIOUS / 'summary.json')
    training, conversion = read(PREVIOUS / 'training.json'), read(PREVIOUS / 'conversion.json')
    if sha(PREVIOUS / 'training.json') != summary['training_sha256'] or summary['plan_sha256'] != sha(PREVIOUS / 'plan.json'):
        raise ValueError('Source training evidence changed')
    if conversion['plan_sha256'] != sha(PREVIOUS / 'plan.json'):
        raise ValueError('Source conversion identity differs')
    for filename, expected in old['scoring_sha256'].items():
        if sha(PREVIOUS / 'scoring' / filename) != expected:
            raise ValueError('Source references or baseline changed')
        save(ROOT / 'scoring' / filename, read(PREVIOUS / 'scoring' / filename))
    if sha(PREVIOUS / 'inputs.json') != old['inputs_sha256']:
        raise ValueError('Source input population changed')
    if sha(REPO / 'data/curated/nus-convergence-v1/subset.jsonl') != old['subset_sha256']:
        raise ValueError('The original 32 train pairs changed')
    save(ROOT / 'inputs.json', read(PREVIOUS / 'inputs.json'))
    save(ROOT / 'scoring/previous-fit.json', read(PREVIOUS / 'fit-comparison.json'))
    execution = read(PREVIOUS / 'fit-240/execution.json')
    if execution['plan_sha256'] != sha(PREVIOUS / 'plan.json') or execution['runtime_failures']:
        raise ValueError('Source fit execution is not a successful matching run')
    if sha(PREVIOUS / 'fit-comparison.json') != summary['fit_comparison_sha256']:
        raise ValueError('Source fit comparison changed')
    records = {}
    for filename, expected in execution['prediction_sha256'].items():
        path = PREVIOUS / 'fit-240/predictions' / filename
        if sha(path) != expected:
            raise ValueError('Source fit answer changed')
        record = read(path)
        records[record['id']] = record
    save(ROOT / 'scoring/source-fit.json', records)
    frozen = ROOT / 'frozen'
    for directory in ('src', 'scripts', 'configs', 'tests'):
        shutil.copytree(REPO / directory, frozen / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / filename, frozen / filename)
    hashes = {p.relative_to(frozen).as_posix(): sha(p) for p in sorted(frozen.rglob('*')) if p.is_file()}
    save(ROOT / 'frozen-files.json', hashes)
    plan = {k: old[k] for k in ('subset_sha256', 'selected_ids', 'base_manifest', 'config',
        'parent_model', 'fit_duration_sec', 'permission_evidence_sha256')}
    plan.update(frozen_at=datetime.now(UTC).isoformat(),
        implementation_sha256={k: v for k, v in hashes.items() if k.startswith(('src/', 'scripts/')) or
            k in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml', 'uv.lock')},
        protocol_sha256=sha(ROOT / 'protocol.md'), inputs_sha256=sha(ROOT / 'inputs.json'),
        previous_plan_sha256=sha(PREVIOUS / 'plan.json'),
        scoring_sha256={p.name: sha(p) for p in (ROOT / 'scoring').iterdir()},
        source_model=conversion['models']['240'],
        model_names={str(step): f'whisper-small-nus-continuation-v1-add{step}' for step in (160, 400)},
        continuation={'source_step': 240, 'additional_steps': 400, 'learning_rate': 2e-5,
            'schedule': 'constant', 'milestones': [160, 400], 'restore_optimizer': True,
            'restore_scaler': True, 'unconditional_transfer': True,
            'source_checkpoint_files': training['checkpoints']['240'],
            'source_training_sha256': sha(PREVIOUS / 'training.json')},
        budgets={'new_training_arms': 1, 'additional_steps': 400, 'fit_ASR': 64,
                 'transfer_ASR': 804, 'CPU_smoke': 1},
        quality_evidence=False, test_accessed=False, release_promoted=False)
    from north55_speech.continuation import validate_continuation
    validate_continuation(plan)
    save(ROOT / 'plan.json', plan)
    print('Frozen continuation: +400 steps, two fit milestones, before/after transfer on the same 402 inputs.', flush=True)


def initialize_volume():
    name = 'north55-nus-continuation-volume-init-v1'
    command = ['docker', 'run', '--name', name, '--network', 'none', '--user', '0:0',
        '-v', launch.VOLUME + ':/experiment', '--entrypoint', 'python', launch.IMAGE, '-c',
        "from pathlib import Path; import os; p=Path('/experiment').resolve(); "
        "assert str(p)=='/experiment' and not any(p.iterdir()), 'Only initialize an empty named experiment volume'; "
        "os.chown(p,10001,10001); print('Initialized empty experiment volume')"]
    subprocess.run(command, check=True)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(ROOT / 'volume-initialization.json', {'image': obj['Image'], 'state': obj['State'],
         'network': obj['HostConfig']['NetworkMode'], 'mounts': obj['Mounts'], 'volume': launch.VOLUME})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'init', 'tests', 'train', 'convert', 'fit', 'transfer', 'cpu', 'score-transfer'])
    parser.add_argument('step', nargs='?', type=int, choices=[0, 160, 400])
    args = parser.parse_args()
    if args.stage in ('fit', 'transfer', 'cpu') and args.step is None:
        parser.error('step is required')
    if args.stage == 'freeze':
        freeze()
    elif args.stage == 'init':
        initialize_volume()
    else:
        launch.run(args.stage, args.step)
