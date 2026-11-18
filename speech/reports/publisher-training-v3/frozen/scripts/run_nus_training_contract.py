"""Portable launcher for a frozen training-only diagnosis; no source or model writes."""

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from scripts.audit_nus_training_contract import read, save, sha, validate_inputs

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / 'reports/nus-training-contract-v1'
IMAGE = 'north55-speech-train:publisher-v2'


def freeze():
    if (STUDY / 'plan.json').exists() or (STUDY / 'frozen').exists():
        raise ValueError('Preserve the existing freeze')
    previous = REPO / 'reports/nus-diagnosis-v1'
    old = read(previous / 'plan.json')
    training = REPO / 'reports/nus-training-v1/training.json'
    train = REPO / 'data/curated/nus-training-v1/train.jsonl'
    if sha(train) != old['train_manifest_sha256'] or sha(previous / 'inputs.json') != old['inputs_sha256']:
        raise ValueError('Historical inputs changed')
    items = [{k: item[k] for k in ('id', 'audio_path', 'audio_sha256', 'duration_sec', 'input_language')}
             for item in read(previous / 'inputs.json')['fit']]
    validate_inputs(items)
    save(STUDY / 'inputs.json', items)
    frozen = STUDY / 'frozen'
    shutil.copytree(REPO / 'src', frozen / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('scripts/audit_nus_training_contract.py', 'scripts/run_nus_training_contract.py',
                 'tests/test_nus_training_contract.py', 'ACCEPTANCE.yaml', 'SPEC.md', 'SOURCES.md',
                 'configs/baseline.yaml', 'pyproject.toml', 'uv.lock'):
        destination = frozen / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, destination)
    shutil.copyfile(training, STUDY / 'training.json')
    save(STUDY / 'frozen-files.json', {p.relative_to(frozen).as_posix(): sha(p)
                                     for p in sorted(frozen.rglob('*')) if p.is_file()})
    save(STUDY / 'plan.json', {'frozen_at': datetime.now(UTC).isoformat(),
         'inputs_sha256': sha(STUDY / 'inputs.json'), 'train_sha256': sha(train),
         'script_sha256': sha(frozen / 'scripts/audit_nus_training_contract.py'),
         'training_report_sha256': sha(training), 'protocol_sha256': sha(STUDY / 'protocol.md'),
         'frozen_files_sha256': sha(STUDY / 'frozen-files.json'),
         'models': old['models'], 'configs': {s: old['configs'][s + '_on'] for s in ('parent', 'nus')},
         'new_training_steps': 0, 'new_ASR_calls_budget': 550, 'teacher_forcing_passes_budget': 128,
         'test_accessed': False, 'release_promoted': False, 'quality_evidence': False})
    print('Frozen training-only audit: 675 contracts, 32 loss cases, 275 x 2 ASR calls.')


def run(stage):
    plan = read(STUDY / 'plan.json')
    if sha(STUDY / 'protocol.md') != plan['protocol_sha256'] or sha(STUDY / 'frozen-files.json') != plan['frozen_files_sha256']:
        raise ValueError('Frozen plan inputs changed')
    for name, expected in read(STUDY / 'frozen-files.json').items():
        if sha(STUDY / 'frozen' / name) != expected:
            raise ValueError('Frozen code changed')
    output = STUDY / stage
    if output.exists():
        raise ValueError('Preserve previous attempts; choose an audited retry instead')
    output.mkdir()
    name = 'north55-nus-contract-' + stage + '-' + datetime.now(UTC).strftime('%Y%m%d%H%M%S')
    cmd = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
           '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1', '-e', 'CUDA_VISIBLE_DEVICES=0',
           '-e', 'PYTHONPATH=/app:/app/src',
           '-e', 'LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib']
    if stage != 'tests':
        cmd += ['--gpus', 'all']

    def mount(local, remote, ro=True):
        cmd.extend(['-v', str(local).replace('\\', '/') + ':' + remote + (':ro' if ro else '')])

    mount(STUDY / 'frozen', '/app')
    mount(output, '/output', False)
    for name_file in ('plan.json', 'inputs.json'):
        source = STUDY / name_file
        if stage == 'contract-retry' and name_file == 'plan.json':
            amendment = read(STUDY / 'contract-amendment.json')
            for filename, expected in amendment['files'].items():
                if sha(STUDY / 'contract-repair' / filename) != expected:
                    raise ValueError('Audited repair changed')
            source = STUDY / 'contract-repair/plan.json'
            mount(STUDY / 'contract-repair/audit_nus_training_contract.py', '/app/scripts/audit_nus_training_contract.py')
        mount(source, '/study/' + name_file)
    mount('north55-speech_audio_data', '/audio')
    mount('north55-speech_model_cache', '/models')
    if stage in ('contract', 'contract-retry'):
        mount(REPO / 'data/curated/nus-training-v1/train.jsonl', '/train/train.jsonl')
        mount(STUDY / 'training.json', '/study/training.json')
    cmd += [IMAGE, '-u']
    if stage == 'tests':
        cmd += ['-m', 'pytest', '-q', 'tests/test_nus_training_contract.py', '--junitxml=/output/tests.xml']
    else:
        cmd += ['-m', 'scripts.audit_nus_training_contract', 'contract' if stage == 'contract-retry' else stage]
    print('Starting', name, flush=True)
    result = subprocess.run(cmd, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(STUDY / (name + '.json'), {'name': name, 'image': obj['Image'], 'state': obj['State'],
         'network': obj['HostConfig']['NetworkMode'], 'mounts': obj['Mounts'], 'command': cmd})
    (STUDY / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'tests', 'contract', 'contract-retry', 'parent', 'nus'])
    args = parser.parse_args()
    freeze() if args.stage == 'freeze' else run(args.stage)
