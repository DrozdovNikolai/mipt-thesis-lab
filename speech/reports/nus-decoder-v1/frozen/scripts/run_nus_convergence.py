"""PowerShell/Linux launcher for fixed NUS convergence and conditional transfer."""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))

from north55_speech.convergence import select_training_subset  # noqa: E402
from scripts.audit_nus_training_contract import read, save, sha  # noqa: E402

ROOT = REPO / 'reports/nus-convergence-v1'
IMAGE = 'north55-speech-train:publisher-v2'
VOLUME = 'north55-speech_nus_convergence_v1'
SOURCE_VOLUME = None
WORKER = 'scripts.nus_convergence'
TEST_FILE = 'tests/test_convergence.py'
TRAIN_MANIFEST = REPO / 'data/curated/nus-convergence-v1/subset.jsonl'


def freeze():
    if (ROOT / 'frozen').exists() or (ROOT / 'plan.json').exists():
        raise ValueError('Preserve existing freeze')
    original = REPO / 'data/curated/nus-training-v1/train.jsonl'
    previous = REPO / 'reports/nus-lora-ablation-v1'
    old = read(previous / 'build-plan.json')
    training = read(REPO / 'reports/nus-training-v1/training.json')
    if sha(original) != training['train_sha256'] or sha(previous / 'inputs.json') != old['inputs_sha256']:
        raise ValueError('Previously frozen population changed')
    all_samples = [json.loads(line) for line in original.read_text(encoding='utf-8').splitlines()]
    selected = select_training_subset(all_samples)
    ids = [s['sample_id'] for s in selected]
    old_inputs = read(previous / 'inputs.json')
    lookup = {i['id']: i for i in old_inputs['fit']}
    fit = [lookup[key] for key in ids]
    remaining = [i | {'cohort': 'nus_same_source_nonfit'} for i in old_inputs['fit'] if i['id'] not in ids]
    transfer = remaining + old_inputs['control']
    if len(fit) != 32 or len(transfer) != 402:
        raise ValueError('Unexpected fit/transfer population')
    if {i['audio_sha256'] for i in fit} & {i['audio_sha256'] for i in transfer}:
        raise ValueError('Audio overlaps fitting and transfer probes')
    save(ROOT / 'inputs.json', {'fit': fit, 'transfer': transfer})
    subset = REPO / 'data/curated/nus-convergence-v1/subset.jsonl'
    subset.parent.mkdir(parents=True, exist_ok=True)
    with subset.open('x', encoding='utf-8', newline='\n') as stream:
        for sample in selected:
            stream.write(json.dumps(sample, ensure_ascii=False) + '\n')
    for filename, expected in old['scoring_sha256'].items():
        if sha(previous / 'scoring' / filename) != expected:
            raise ValueError('Historical scoring material changed')
    save(ROOT / 'scoring/references.json', read(previous / 'scoring/references.json'))
    parent = read(previous / 'scoring/parent_on.json')
    if any(parent[i['id']]['runtime_failure'] is not None for i in fit + transfer):
        raise ValueError('Historical parent contains runtime failures')
    save(ROOT / 'scoring/parent.json', {i['id']: parent[i['id']] for i in fit + transfer})
    frozen = ROOT / 'frozen'
    for directory in ('src', 'scripts', 'tests', 'configs'):
        shutil.copytree(REPO / directory, frozen / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'pyproject.toml', 'uv.lock'):
        shutil.copyfile(REPO / filename, frozen / filename)
    hashes = {p.relative_to(frozen).as_posix(): sha(p) for p in sorted(frozen.rglob('*')) if p.is_file()}
    save(ROOT / 'frozen-files.json', hashes)
    save(ROOT / 'plan.json', {'frozen_at': datetime.now(UTC).isoformat(),
        'implementation_sha256': {k: v for k, v in hashes.items() if k.startswith(('src/', 'scripts/')) or
                                 k in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'configs/baseline.yaml', 'uv.lock')},
        'protocol_sha256': sha(ROOT / 'protocol.md'), 'inputs_sha256': sha(ROOT / 'inputs.json'),
        'subset_sha256': sha(subset), 'original_train_sha256': sha(original), 'selected_ids': ids,
        'selection': 'first 32 of 275 existing train pairs sorted by audio_sha256, sample_id',
        'base_manifest': training['base_manifest'], 'parent_model': old['models']['parent'],
        'config': old['configs']['parent_on'],
        'model_names': {str(step): f'whisper-small-nus-convergence-v1-step{step}' for step in (40, 120, 240)},
        'scoring_sha256': {p.name: sha(p) for p in (ROOT / 'scoring').iterdir()},
        'training': {'steps': 240, 'seed': 55, 'learning_rate': 5e-5, 'rank': 8, 'alpha': 16,
            'lora_dropout': .05, 'batch_size': 1, 'gradient_accumulation': 4, 'optimizer': 'adamw_torch_fused',
            'schedule': 'linear', 'milestones': [40, 120, 240], 'no_dev_checkpoint_selection': True},
        'transfer_condition': 'Only step 240; run 402 diagnostic records iff final 32-pair train WER <=0.10 with zero runtime failures.',
        'budgets': {'new_training_arms': 1, 'optimizer_steps': 240, 'fit_ASR': 96, 'conditional_transfer_ASR': 402, 'CPU_smoke': 1},
        'scope': 'train fitting plus exposed diagnostic controls, no independent test or release search',
        'fit_duration_sec': sum(s['duration_sec'] for s in selected),
        'permission_evidence_sha256': training['config']['permission_evidence_sha256'],
        'quality_evidence': False, 'test_accessed': False, 'release_promoted': False})
    print('Frozen 32 fitting pairs; milestones 40/120/240; conditional 402-record transfer.', flush=True)


def run(stage, step=None):
    plan = read(ROOT / 'plan.json')
    if sha(ROOT / 'protocol.md') != plan['protocol_sha256']:
        raise ValueError('Frozen protocol changed')
    for name, expected in read(ROOT / 'frozen-files.json').items():
        if sha(ROOT / 'frozen' / name) != expected:
            raise ValueError('Frozen file changed: ' + name)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'north55-nus-convergence-{stage}-{step or "all"}-{stamp}'.lower()
    cmd = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
           '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1', '-e', 'CUDA_VISIBLE_DEVICES=0',
           '-e', 'PYTHONPATH=/app:/app/src',
           '-e', 'LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib']
    if stage in ('train', 'convert', 'fit', 'transfer'):
        cmd += ['--gpus', 'all']

    def mount(local, remote, ro=True):
        cmd.extend(['-v', str(local).replace('\\', '/') + ':' + remote + (':ro' if ro else '')])

    mount(ROOT / 'frozen', '/app')
    mount('north55-speech_model_cache', '/models')
    mount('north55-speech_audio_data', '/audio')
    mount(VOLUME, '/experiment', stage not in ('train', 'convert'))
    if SOURCE_VOLUME:
        mount(SOURCE_VOLUME, '/source_experiment')
    if stage in ('train', 'convert', 'score-fit', 'score-transfer'):
        if stage.startswith('score-'):
            mount(ROOT, '/study', False)
        else:
            for filename in ('plan.json', 'inputs.json'):
                mount(ROOT / filename, '/study/' + filename)
            # Only this stage's output file is writable via its own directory.
            io = ROOT / ('io-' + stage)
            io.mkdir(exist_ok=True)
            mount(io, '/stage-output', False)
            if stage == 'convert':
                mount(ROOT / 'training.json', '/study/training.json')
        if stage == 'train':
            mount(TRAIN_MANIFEST, '/train/subset.jsonl')
    elif stage == 'tests':
        output = ROOT / 'tests'
        output.mkdir(exist_ok=True)
        mount(output, '/results', False)
    else:
        for filename in ('plan.json', 'inputs.json', 'conversion.json'):
            mount(ROOT / filename, '/study/' + filename)
        if stage == 'transfer' and not plan.get('continuation') and not plan.get('decoder_training'):
            mount(ROOT / 'fit-decision.json', '/study/fit-decision.json')
        out = ('cpu-fit' if stage == 'cpu' else stage) + f'-{step}'
        (ROOT / out).mkdir(exist_ok=True)
        mount(ROOT / out, '/study/' + out, False)
    if stage == 'tests':
        cmd += [IMAGE, '-m', 'pytest', '-q', TEST_FILE, '--junitxml=/results/results.xml']
    else:
        # Set only the report output location, leaving frozen inputs read-only.
        if stage in ('train', 'convert'):
            cmd += ['-e', 'NORTH55_DIAGNOSTIC_OUTPUT=/stage-output']
        cmd += [IMAGE, '-u', '-m', WORKER, stage]
        if step is not None:
            cmd += [str(step)]
    print('Starting', name, flush=True)
    result = subprocess.run(cmd, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(ROOT / (name + '.json'), {'name': name, 'image': obj['Image'], 'state': obj['State'],
        'network': obj['HostConfig']['NetworkMode'], 'command': obj['Config']['Cmd'], 'mounts': obj['Mounts']})
    (ROOT / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)
    if stage in ('train', 'convert'):
        filename = 'training.json' if stage == 'train' else 'conversion.json'
        with (ROOT / filename).open('xb') as stream:
            stream.write((ROOT / ('io-' + stage) / filename).read_bytes())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'tests', 'train', 'convert', 'fit', 'transfer', 'cpu', 'score-fit', 'score-transfer'])
    parser.add_argument('step', nargs='?', type=int, choices=[40, 120, 240])
    args = parser.parse_args()
    if args.stage in ('fit', 'transfer', 'cpu') and args.step is None:
        parser.error('step is required')
    freeze() if args.stage == 'freeze' else run(args.stage, args.step)
