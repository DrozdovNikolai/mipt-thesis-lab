"""Portable launcher for a frozen repair experiment, isolated from prior answers."""

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'reports/text-window-fix-v1'
SYSTEMS = ('parent_reference', 'parent_text', 'augmented_reference', 'augmented_text')


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def freeze():
    frozen = ROOT / 'frozen'
    if frozen.exists():
        raise ValueError('Preserve frozen sources')
    frozen.mkdir()
    for directory in ('src', 'scripts', 'tests', 'configs'):
        shutil.copytree(REPO / directory, frozen / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / name, frozen / name)
    for name in (*SYSTEMS, 'cpu-parent_text', 'cpu-augmented_text', 'regressions'):
        (ROOT / name).mkdir(exist_ok=True)
    save(ROOT / 'frozen-files.json', {p.relative_to(frozen).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted(frozen.rglob('*')) if p.is_file()})


def run(action, system):
    frozen = ROOT / 'frozen'
    if not frozen.exists():
        raise ValueError('Freeze source first')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'north55-text-window-fix-{action}-{system or "all"}-{stamp}'.lower()
    args = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
            '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1']
    if action in ('infer', 'regression'):
        args += ['--gpus', 'all']
    def mount(local, remote, ro=True):
        args.extend(['-v', f'{local}:{remote}' + (':ro' if ro else '')])
    for directory in ('src', 'scripts', 'configs'):
        mount((frozen / directory).as_posix(), '/app/' + directory)
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock'):
        mount((frozen / filename).as_posix(), '/app/' + filename)
    mount('north55-speech_audio_data', '/audio')
    mount('north55-speech_model_cache', '/models')
    if action in ('infer', 'cpu', 'regression'):
        for filename in ('plan.json', 'inputs.json', 'protocol.md'):
            mount((ROOT / filename).as_posix(), '/study/' + filename)
        directory = 'regressions' if action == 'regression' else ('cpu-' if action == 'cpu' else '') + system
        mount((ROOT / directory).as_posix(), '/study/' + directory, False)
    else:
        mount(ROOT.as_posix(), '/study', False)
    if action == 'prepare':
        mount((REPO / 'reports/decoding-v1').as_posix(), '/prior')
        if ROOT.name == 'text-window-fix-v2':
            mount((REPO / 'reports/text-window-fix-v1/plan.json').as_posix(), '/first-repair-plan.json')
    if action == 'score':
        mount((REPO / 'data/curated/language-large-v1/scoring/references.json').as_posix(), '/scoring/references.json')
    if action == 'tests':
        mount((frozen / 'tests').as_posix(), '/app/tests')
    args += ['north55-speech-gpu:0.1.0']
    if action == 'tests':
        args += ['-m', 'pytest', 'tests/test_text_windows.py', 'tests/test_decoding_diagnostics.py', '-q', f'--junitxml=/study/tests-{stamp}.xml']
    elif action == 'regression':
        args += ['-u', '-m', 'scripts.text_window_regression']
    else:
        args += ['-u', '-m', 'scripts.text_window_experiment', action]
        if system:
            args += ['--system', system]
    print(' '.join(args), flush=True)
    proc = subprocess.run(args, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(ROOT / (name + '.json'), {'name': name, 'image_id': obj['Image'],
        'network_mode': obj['HostConfig']['NetworkMode'], 'state': obj['State'], 'command': obj['Config']['Cmd'],
        'mounts': [{k: m[k] for k in ('Type', 'Source', 'Destination', 'RW')} for m in obj['Mounts']]})
    (ROOT / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if proc.returncode:
        raise SystemExit(proc.returncode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'prepare', 'infer', 'cpu', 'regression', 'tests', 'score'))
    parser.add_argument('--system', choices=SYSTEMS)
    parser.add_argument('--study', choices=('text-window-fix-v1', 'text-window-fix-v2'), default='text-window-fix-v1')
    args = parser.parse_args()
    ROOT = REPO / 'reports' / args.study
    if args.action in ('infer', 'cpu') and not args.system:
        parser.error('--system required')
    if args.action == 'freeze':
        freeze()
    else:
        run(args.action, args.system)
