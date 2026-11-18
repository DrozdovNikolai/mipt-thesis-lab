"""Portable, isolated Docker stages for the NUS training experiment."""

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / 'reports/nus-training-v1'
DATA = REPO / 'data/curated/nus-training-v1'
EVALUATION = STUDY / ('evaluation-v2' if (STUDY / 'cuda-runtime-retry.json').exists() else 'evaluation')


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def freeze():
    frozen = STUDY / 'frozen'
    if frozen.exists():
        raise ValueError('Preserve frozen experiment')
    frozen.mkdir(parents=True)
    for directory in ('src', 'scripts', 'configs', 'tests'):
        shutil.copytree(REPO / directory, frozen / directory,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / name, frozen / name)
    save(STUDY / 'frozen-files.json', {p.relative_to(frozen).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(frozen.rglob('*')) if p.is_file()})
    DATA.mkdir(parents=True, exist_ok=True)
    for name in ('nus', 'cpu-nus', 'historical'):
        (STUDY / 'evaluation' / name).mkdir(parents=True, exist_ok=True)
    save(STUDY / 'scoring-identity.json', {
        'recorded_at_before_training': datetime.now(UTC).isoformat(),
        'script_sha256': hashlib.sha256((frozen / 'scripts/score_nus_retraining.py').read_bytes()).hexdigest()})


def run(stage):
    source = STUDY / 'frozen'
    if not source.exists():
        raise ValueError('Freeze first')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'north55-nus-v1-{stage}-{stamp}'.lower()
    args = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
            '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1']
    if stage in ('train', 'infer'):
        args += ['--gpus', 'all']
    args += ['-e', 'LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib']

    def mount(local, remote, readonly=True):
        args.extend(['-v', f'{local}:{remote}' + (':ro' if readonly else '')])

    for directory in ('src', 'scripts', 'configs'):
        mount((source / directory).as_posix(), '/app/' + directory)
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock'):
        mount((source / filename).as_posix(), '/app/' + filename)
    if stage not in ('score', 'tests'):
        mount('north55-speech_audio_data', '/audio', stage != 'prepare')
        mount('north55-speech_model_cache', '/models', stage != 'train')
    if stage in ('prepare', 'train', 'freeze-eval', 'tests'):
        mount(STUDY.as_posix(), '/study', False)
        mount(DATA.as_posix(), '/dataset', stage != 'prepare')
    if stage == 'prepare':
        for filename in ('train.jsonl', 'dev.jsonl'):
            mount((REPO / 'data/curated/balanced-v1' / filename).as_posix(), '/old/' + filename)
        for filename in ('plan.json', 'inputs.json'):
            mount((REPO / 'reports/balanced-v1' / filename).as_posix(), '/old/' + filename)
        mount((REPO / 'reports/balanced-v1/split-metadata/reviewed-dev.jsonl').as_posix(), '/old/reviewed-dev.jsonl')
        mount((REPO / 'data/quarantine/nus-vr-v1').as_posix(), '/source')
        mount((REPO / 'reports/nus-vr-v1').as_posix(), '/source-audit')
    if stage == 'freeze-eval':
        mount((REPO / 'reports/balanced-v1/evaluation').as_posix(), '/previous-eval')
    if stage in ('infer', 'cpu'):
        for filename in ('plan.json', 'inputs.json', 'protocol.md'):
            mount((EVALUATION / filename).as_posix(), '/eval/' + filename)
        output = 'nus' if stage == 'infer' else 'cpu-nus'
        mount((EVALUATION / output).as_posix(), '/eval/' + output, False)
    if stage == 'score':
        mount(EVALUATION.as_posix(), '/eval', False)
        mount((REPO / 'data/curated/language-large-v1/scoring/references.json').as_posix(), '/scoring/references.json')
    if stage == 'tests':
        mount((source / 'tests').as_posix(), '/app/tests')
    # Frozen driver imports PyArrow at module load; use the complete local runtime.
    # It already executed the saved CT2 GPU smoke; ASR library versions are unchanged.
    args += ['north55-speech-gpu:0.1.0' if stage == 'score' else 'north55-speech-train:publisher-v2']
    if stage == 'tests':
        args += ['-m', 'pytest', 'tests/test_nus_training.py', 'tests/test_retraining.py',
                 'tests/test_quality_pair_groups.py', 'tests/test_nus_vr_inspection.py',
                 '-q', f'--junitxml=/study/tests-{stamp}.xml']
    elif stage == 'score':
        args += ['-u', '-m', 'scripts.score_nus_retraining']
    else:
        args += ['-u', '-m', 'scripts.nus_retraining', stage]
    print(' '.join(args), flush=True)
    result = subprocess.run(args, check=False)
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(STUDY / (name + '.json'), {'name': name, 'image_id': obj['Image'],
        'network_mode': obj['HostConfig']['NetworkMode'], 'state': obj['State'], 'command': obj['Config']['Cmd'],
        'runtime_environment': [value for value in obj['Config']['Env'] if value.startswith(('LD_LIBRARY_PATH=', 'CUDA_VISIBLE_DEVICES=', 'HF_HUB_OFFLINE=', 'TRANSFORMERS_OFFLINE='))],
        'mounts': [{k: m[k] for k in ('Type', 'Source', 'Destination', 'RW')} for m in obj['Mounts']]})
    (STUDY / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'prepare', 'train', 'freeze-eval', 'infer', 'cpu', 'score', 'tests'))
    stage = parser.parse_args().stage
    freeze() if stage == 'freeze' else run(stage)
