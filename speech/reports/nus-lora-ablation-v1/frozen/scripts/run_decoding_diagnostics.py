"""Identical offline Docker invocation from PowerShell and Linux/WSL."""

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / 'reports/decoding-v1'
SYSTEMS = tuple(f'{m}_{v}' for m in ('parent', 'augmented') for v in ('baseline', 'text', 'vad'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def freeze():
    root = STUDY / 'frozen'
    if root.exists():
        raise ValueError('Preserve frozen sources')
    root.mkdir(parents=True)
    for directory in ('src', 'scripts', 'configs', 'tests'):
        shutil.copytree(REPO / directory, root / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / name, root / name)
    for name in (*SYSTEMS, 'cpu-parent_text', 'cpu-parent_vad', 'cpu-augmented_text', 'cpu-augmented_vad'):
        (STUDY / name).mkdir(exist_ok=True)
    write(STUDY / 'frozen-files.json', {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(root.rglob('*')) if p.is_file()})
    print('Frozen source snapshot created', flush=True)


def run(action, system):
    frozen = STUDY / 'frozen'
    source = frozen if frozen.exists() else REPO
    if action != 'tests' and not frozen.exists():
        raise ValueError('Freeze the code first')
    attempt = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'north55-decoding-v1-{action}-{system or "all"}-{attempt}'.lower()
    args = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
            '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1']
    if action == 'infer':
        args += ['--gpus', 'all']
    def mount(local, remote, readonly=True):
        args.extend(['-v', f'{local}:{remote}' + (':ro' if readonly else '')])
    for directory in ('scripts', 'src', 'configs'):
        mount((source / directory).as_posix(), '/app/' + directory)
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock'):
        mount((source / filename).as_posix(), '/app/' + filename)
    mount('north55-speech_audio_data', '/audio')
    mount('north55-speech_model_cache', '/models')
    if action in ('infer', 'cpu'):
        # No references, historical answers, training data, or other systems.
        for filename in ('plan.json', 'inputs.json', 'protocol.md'):
            mount((STUDY / filename).as_posix(), '/study/' + filename)
        output_name = ('cpu-' if action == 'cpu' else '') + system
        mount((STUDY / output_name).as_posix(), '/study/' + output_name, False)
    else:
        mount(STUDY.as_posix(), '/study', False)
    if action == 'prepare':
        mount((REPO / 'reports/retraining-v1/evaluation').as_posix(), '/prior')
    if action == 'score':
        mount((REPO / 'data/curated/language-large-v1/scoring/references.json').as_posix(), '/scoring/references.json')
    if action == 'tests':
        mount((source / 'tests').as_posix(), '/app/tests')
    args += ['north55-speech-gpu:0.1.0']
    if action == 'tests':
        args += ['-m', 'pytest', 'tests/test_decoding_diagnostics.py', '-q', f'--junitxml=/study/tests-{attempt}.xml']
    else:
        args += ['-u', '-m', 'scripts.decoding_diagnostics', action]
        if system:
            args += ['--system', system]
    print(' '.join(args), flush=True)
    result = subprocess.run(args, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    write(STUDY / (name + '.json'), {'name': name, 'image_id': obj['Image'],
        'network_mode': obj['HostConfig']['NetworkMode'], 'command': obj['Config']['Cmd'],
        'state': obj['State'], 'mounts': [{k: m[k] for k in ('Type', 'Source', 'Destination', 'RW')} for m in obj['Mounts']],
        'environment': [e for e in obj['Config']['Env'] if e.startswith(('CUDA_VISIBLE_DEVICES=', 'HF_HUB_OFFLINE=', 'TRANSFORMERS_OFFLINE='))]})
    (STUDY / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'prepare', 'tests', 'infer', 'cpu', 'score'))
    parser.add_argument('--system', choices=SYSTEMS)
    args = parser.parse_args()
    if args.action in ('infer', 'cpu') and not args.system:
        parser.error('--system required')
    if args.action == 'freeze':
        freeze()
    else:
        run(args.action, args.system)
