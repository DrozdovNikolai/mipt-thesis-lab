"""Portable launcher for one balanced-sampling experiment with isolated mounts."""

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / 'reports/balanced-v1'
DATA = REPO / 'data/curated/balanced-v1'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def freeze():
    frozen = STUDY / 'frozen'
    if frozen.exists():
        raise ValueError('Frozen experiment exists')
    frozen.mkdir(parents=True)
    for directory in ('src', 'scripts', 'configs', 'tests'):
        shutil.copytree(REPO / directory, frozen / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / name, frozen / name)
    save(STUDY / 'frozen-files.json', {p.relative_to(frozen).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted(frozen.rglob('*')) if p.is_file()})
    DATA.mkdir(parents=True, exist_ok=True)
    for name in ('balanced', 'cpu-balanced', 'historical'):
        (STUDY / 'evaluation' / name).mkdir(parents=True, exist_ok=True)


def run(stage):
    source = STUDY / 'frozen'
    if not source.exists():
        raise ValueError('Freeze first')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'north55-balanced-v1-{stage}-{stamp}'.lower()
    args = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
            '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1']
    if stage in ('train', 'infer'):
        args += ['--gpus', 'all']

    def mount(local, remote, readonly=True):
        args.extend(['-v', f'{local}:{remote}' + (':ro' if readonly else '')])

    for directory in ('src', 'scripts', 'configs'):
        mount((source / directory).as_posix(), '/app/' + directory)
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock'):
        mount((source / filename).as_posix(), '/app/' + filename)
    mount('north55-speech_audio_data', '/audio', stage != 'prepare')
    mount('north55-speech_model_cache', '/models', stage != 'train')
    if stage in ('prepare', 'train', 'freeze-eval', 'tests'):
        mount(STUDY.as_posix(), '/study', False)
        mount(DATA.as_posix(), '/dataset', stage != 'prepare')
    if stage == 'prepare':
        # Only train transcripts and known dev split metadata; no final-test mount.
        mount((REPO / 'data/curated/retraining-v1/augmented/train.jsonl').as_posix(), '/old/train.jsonl')
        mount((REPO / 'data/curated/retraining-v1/dev.jsonl').as_posix(), '/old/dev.jsonl')
        mount((REPO / 'reports/retraining-v1/plan.json').as_posix(), '/previous-plan.json')
        mount((REPO / 'reports/retraining-v1/frozen/src/north55_speech/lora.py').as_posix(), '/old-lora.py')
        mount((REPO / 'data/input/pair-quality-sources-v1').as_posix(), '/sources')
        mount((REPO / 'reports/retraining-v1/inputs.json').as_posix(), '/input-source.json')
        mount((REPO / 'reports/decoding-v1/inputs.json').as_posix(), '/quiet-source.json')
        mount((STUDY / 'split-metadata/clean-plan.json').as_posix(), '/clean-plan.json')
        mount((STUDY / 'split-metadata/reviewed-dev.jsonl').as_posix(), '/reviewed-dev.jsonl')
    if stage == 'freeze-eval':
        mount((REPO / 'reports/retraining-v1/evaluation').as_posix(), '/previous-eval')
        mount((REPO / 'reports/decoding-v1').as_posix(), '/quiet-history')
    if stage in ('infer', 'cpu'):
        for filename in ('plan.json', 'inputs.json', 'protocol.md'):
            mount((STUDY / 'evaluation' / filename).as_posix(), '/eval/' + filename)
        name_out = 'balanced' if stage == 'infer' else 'cpu-balanced'
        mount((STUDY / 'evaluation' / name_out).as_posix(), '/eval/' + name_out, False)
    image = 'north55-speech-train:publisher-v2' if stage in ('prepare', 'train') else 'north55-speech-gpu:0.1.0'
    if stage == 'tests':
        mount((source / 'tests').as_posix(), '/app/tests')
    args += [image]
    if stage == 'tests':
        args += ['-m', 'pytest', 'tests/test_balanced_sampling.py', 'tests/test_retraining.py',
                 'tests/test_quality_pair_groups.py', '-q', f'--junitxml=/study/tests-{stamp}.xml']
    else:
        args += ['-u', '-m', 'scripts.balanced_retraining', stage]
    print(' '.join(args), flush=True)
    result = subprocess.run(args, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(STUDY / (name + '.json'), {'name': name, 'image_id': obj['Image'],
        'network_mode': obj['HostConfig']['NetworkMode'], 'state': obj['State'], 'command': obj['Config']['Cmd'],
        'mounts': [{k: m[k] for k in ('Type', 'Source', 'Destination', 'RW')} for m in obj['Mounts']]})
    (STUDY / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'prepare', 'train', 'freeze-eval', 'infer', 'cpu', 'tests'))
    stage = parser.parse_args().stage
    freeze() if stage == 'freeze' else run(stage)
