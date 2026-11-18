"""Portable Docker launcher. PowerShell/Linux wrappers call this exact implementation."""
import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / 'reports/retraining-v1'
DATA = REPO / 'data/curated/retraining-v1'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def freeze():
    root = STUDY / 'frozen'
    if root.exists():
        raise ValueError('Frozen source exists; preserve it')
    root.mkdir(parents=True)
    for name in ('src', 'scripts', 'configs', 'tests'):
        shutil.copytree(REPO / name, root / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / name, root / name)
    write(STUDY / 'frozen-files.json', {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(root.rglob('*')) if p.is_file()})
    print('Frozen source snapshot created', flush=True)


def run(stage, selected=None, resume=False):
    frozen = STUDY / 'frozen'
    if stage != 'tests' and not frozen.exists():
        raise ValueError('Run freeze first')
    source = frozen if frozen.exists() else REPO
    name = 'north55-retraining-v1-' + stage + (('-' + selected) if selected else '')
    existing = subprocess.check_output(['docker', 'ps', '-a', '--filter', f'name=^/{name}$', '--format', '{{.Names}}'], text=True).strip()
    if existing and stage == 'tests':
        name += '-' + datetime.now(UTC).strftime('%Y%m%d%H%M%S')
        existing = ''
    if existing and not (resume and stage == 'infer'):
        raise ValueError(f'Preserve existing {name}; only completed inference supports --resume')
    if resume and not existing:
        raise ValueError('No inference container to resume')
    def mount(local, remote, readonly=True):
        return ['-v', f'{local}:{remote}' + (':ro' if readonly else '')]
    args = ['docker', 'run', '--name', name, '--network', 'none',
            '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1',
            '--entrypoint', 'python']
    if stage in ('train', 'infer'):
        args += ['--gpus', 'all']
    for directory in ('scripts', 'src', 'configs'):
        args += mount((source / directory).as_posix(), '/app/' + directory)
    for file in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock'):
        args += mount((source / file).as_posix(), '/app/' + file)
    args += mount('north55-speech_audio_data', '/audio')
    args += mount('north55-speech_model_cache', '/models', stage != 'train')
    if stage in ('prepare', 'train', 'freeze-eval', 'tests'):
        DATA.mkdir(parents=True, exist_ok=True)
        args += mount(STUDY.as_posix(), '/study', False)
        args += mount(DATA.as_posix(), '/dataset', stage != 'prepare')
    if stage == 'prepare':
        args += mount((REPO / 'data/curated/publisher-expanded-v1/training').as_posix(), '/old')
        args += mount((REPO / 'data/curated/training-support-v1').as_posix(), '/support')
        args += mount((REPO / 'reports/language-large-v1/inputs.json').as_posix(), '/input-source.json')
        args += mount((REPO / 'reports/language-large-v1/plan.json').as_posix(), '/previous-plan.json')
    if stage in ('infer', 'cpu'):
        for file in ('plan.json', 'inputs.json', 'protocol.md'):
            args += mount((STUDY / 'evaluation' / file).as_posix(), '/eval/' + file)
        if stage == 'infer':
            output = STUDY / 'evaluation' / selected
            try:
                output.mkdir(exist_ok=True)
            except PermissionError:
                # Existing Windows/WSL outputs may belong to image UID 10001.
                # Let that same owner create this leaf; do not relax permissions.
                subprocess.run(['docker', 'run', '--rm', '--network', 'none',
                    '--entrypoint', 'python', '-v', f'{output.parent.as_posix()}:/output',
                    'north55-speech-gpu:0.1.0', '-c',
                    'from pathlib import Path; import sys; Path("/output", sys.argv[1]).mkdir(exist_ok=True)',
                    selected], check=True)
            args += mount(output.as_posix(), '/eval/' + selected, False)
        else:
            output = STUDY / 'smoke'
            output.mkdir(exist_ok=True)
            args += mount(output.as_posix(), '/smoke', False)
    if stage == 'score':
        args += mount((STUDY / 'evaluation').as_posix(), '/eval', False)
        args += mount((REPO / 'data/curated/language-large-v1/scoring/references.json').as_posix(), '/scoring/references.json')
    args += ['north55-speech-train:publisher-v2' if stage == 'train' else 'north55-speech-gpu:0.1.0']
    if stage == 'tests':
        # Insert test mount before image, not in the command arguments.
        args[-1:-1] = mount((source / 'tests').as_posix(), '/app/tests')
        args += ['-m', 'pytest', 'tests/test_retraining.py', 'tests/unit/test_publisher_training.py',
                 'tests/test_quality_pair_groups.py', 'tests/test_training_support_import.py',
                 '-q', f'--junitxml=/study/{name}.xml']
    else:
        args += ['-u', '-m', 'scripts.retrain_asr', stage]
        if stage == 'train':
            args += ['--arm', selected]
        if stage == 'infer':
            args += ['--system', selected]
    if resume:
        args = ['docker', 'start', '-a', name]
    print(' '.join(args), flush=True)
    result = subprocess.run(args, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    suffix = '-resume' if resume else ''
    if resume and (STUDY / (name + suffix + '.json')).exists():
        suffix += '-' + datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')
    write(STUDY / (name + suffix + '.json'), {'name': name, 'image_id': obj['Image'],
        'network_mode': obj['HostConfig']['NetworkMode'], 'command': obj['Config']['Cmd'],
        'state': obj['State'], 'mounts': [{k: m[k] for k in ('Type', 'Source', 'Destination', 'RW')} for m in obj['Mounts']],
        'environment': [e for e in obj['Config']['Env'] if e.startswith(('CUDA_VISIBLE_DEVICES=', 'HF_HUB_OFFLINE=', 'TRANSFORMERS_OFFLINE='))]})
    (STUDY / (name + suffix + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('freeze', 'prepare', 'train', 'freeze-eval', 'infer', 'score', 'cpu', 'tests'))
    p.add_argument('--selected', choices=('parent', 'control', 'augmented'))
    p.add_argument('--resume', action='store_true')
    a = p.parse_args()
    if a.stage in ('train', 'infer') and not a.selected:
        p.error('--selected required')
    if a.stage == 'train' and a.selected == 'parent':
        p.error('Parent must stay unadapted')
    if a.stage == 'freeze':
        freeze()
    else:
        run(a.stage, a.selected, a.resume)
