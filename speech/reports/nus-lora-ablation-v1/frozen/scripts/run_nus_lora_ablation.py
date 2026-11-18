"""Portable, bounded saved-adapter ablation. No training or network access."""

import argparse
import shutil
import subprocess
from datetime import UTC, datetime

from scripts.run_nus_failure_diagnosis import IMAGE, REPO, read, save, sha

ROOT = REPO / 'reports/nus-lora-ablation-v1'
PRIOR = REPO / 'reports/nus-diagnosis-v1'


def freeze():
    if (ROOT / 'frozen').exists():
        raise ValueError('Preserve frozen study')
    prior = read(PRIOR / 'plan.json')
    if sha(PRIOR / 'inputs.json') != prior['inputs_sha256']:
        raise ValueError('Previous input identity changed')
    old_inputs = read(PRIOR / 'inputs.json')
    all_items = old_inputs['context']
    control = [i for i in all_items if i['cohort'] in ('partial_human_dev', 'general_clean', 'general_ru',
                                                       'quiet_partial_human_dev', 'quiet_general_clean')]
    for cohort in ('noise_only', 'bleriot_b_noise'):
        duration = 0.
        for item in sorted((i for i in all_items if i['cohort'] == cohort), key=lambda i: (i['audio_sha256'], i['id'])):
            control.append(item)
            duration += item['duration_sec']
            if duration >= 300:
                break
        if duration < 300:
            raise ValueError('Insufficient noise control duration')
    save(ROOT / 'inputs.json', {'fit': old_inputs['fit'], 'control': control})
    for filename, expected in prior['scoring_sha256'].items():
        if sha(PRIOR / 'scoring' / filename) != expected:
            raise ValueError('Previous scoring material changed')
    references = read(PRIOR / 'scoring/dev-references.json') | read(PRIOR / 'scoring/fit-references.json')
    save(ROOT / 'scoring/references.json', references)
    for base in ('parent', 'nus'):
        records = read(PRIOR / 'scoring' / (base + '.json'))
        directory = PRIOR / ('fit-' + base + '_on')
        execution = read(directory / 'execution.json')
        if execution['plan_sha256'] != sha(PRIOR / 'plan.json'):
            raise ValueError('Fitting run identity changed')
        for filename, expected in execution['prediction_sha256'].items():
            path = directory / 'predictions' / filename
            if sha(path) != expected:
                raise ValueError('Fitting answer changed')
            record = read(path)
            records[record['id']] = record
        save(ROOT / 'scoring' / (base + '_on.json'), {i['id']: records[i['id']] for i in old_inputs['fit'] + control})
    frozen = ROOT / 'frozen'
    for directory in ('src', 'scripts', 'configs', 'tests'):
        shutil.copytree(REPO / directory, frozen / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'pyproject.toml'):
        shutil.copyfile(REPO / name, frozen / name)
    hashes = {p.relative_to(frozen).as_posix(): sha(p) for p in sorted(frozen.rglob('*')) if p.is_file()}
    save(ROOT / 'frozen-files.json', hashes)
    save(ROOT / 'build-plan.json', {'frozen_at': datetime.now(UTC).isoformat(),
        'models': prior['models'], 'configs': {s: prior['configs'][s] for s in ('parent_on', 'nus_on')},
        'implementation_sha256': {k: v for k, v in hashes.items() if k.startswith(('src/', 'scripts/')) or
            k in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock', 'configs/baseline.yaml')},
        'inputs_sha256': sha(ROOT / 'inputs.json'), 'protocol_sha256': sha(ROOT / 'protocol.md'),
        'training_sha256': sha(REPO / 'reports/nus-training-v1/training.json'),
        'scoring_sha256': {p.name: sha(p) for p in (ROOT / 'scoring').glob('*.json')},
        'train_inputs': len(old_inputs['fit']), 'control_inputs': len(control), 'new_training_steps': 0,
        'component_arms': ['encoder', 'decoder'], 'test_accessed': False, 'release_promoted': False,
        'quality_evidence': False, 'selection_allowed': False})
    print(f'Frozen: 275 train fitting pairs, {len(control)} control inputs, two component arms, zero training steps.')


def run(stage, part):
    frozen = ROOT / 'frozen'
    for name, expected in read(ROOT / 'frozen-files.json').items():
        if sha(frozen / name) != expected:
            raise ValueError('Frozen implementation changed')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'north55-nus-components-{stage}-{part or "all"}-{stamp}'.lower()
    args = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python',
        '-e', 'CUDA_VISIBLE_DEVICES=0', '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1',
        '-e', 'LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib']
    if stage in ('fit', 'control'):
        args += ['--gpus', 'all']

    def mount(local, remote, ro=True):
        args.extend(['-v', str(local).replace('\\', '/') + ':' + remote + (':ro' if ro else '')])

    for directory in ('src', 'scripts', 'configs', 'tests'):
        mount(frozen / directory, '/app/' + directory)
    for filename in ('SPEC.md', 'SOURCES.md', 'ACCEPTANCE.yaml', 'uv.lock'):
        mount(frozen / filename, '/app/' + filename)
    mount('north55-speech_model_cache', '/models', stage != 'merge')
    if stage in ('merge', 'score'):
        mount(ROOT, '/study', False)
        if stage == 'merge':
            mount(REPO / 'reports/nus-training-v1/training.json', '/source/training.json')
    elif stage == 'tests':
        mount(ROOT / 'tests', '/results', False)
    else:
        for filename in ('plan.json', 'protocol.md', 'inputs.json'):
            mount(ROOT / filename, '/study/' + filename)
        mount('north55-speech_audio_data', '/audio')
        output = ('cpu-control' if stage == 'cpu' else stage) + '-' + part + '_on'
        (ROOT / output).mkdir(exist_ok=True)
        mount(ROOT / output, '/study/' + output, False)
    if stage == 'tests':
        args += [IMAGE, '-m', 'pytest', 'tests/test_lora_ablation.py', '-q', '--junitxml=/results/results.xml']
    else:
        args += [IMAGE, '-u', '-m', 'scripts.nus_lora_ablation', stage]
        if part:
            args += [part]
    print('Starting ' + name, flush=True)
    result = subprocess.run(args, check=False)
    import json
    obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    save(ROOT / (name + '.json'), {'name': name, 'image_id': obj['Image'], 'network_mode': obj['HostConfig']['NetworkMode'],
        'state': obj['State'], 'command': obj['Config']['Cmd'], 'mounts': [{k: m[k] for k in ('Type', 'Source', 'Destination', 'RW')} for m in obj['Mounts']]})
    (ROOT / (name + '.log')).write_bytes(subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze', 'merge', 'fit', 'control', 'cpu', 'score', 'tests'))
    parser.add_argument('part', nargs='?', choices=('encoder', 'decoder'))
    args = parser.parse_args()
    if args.stage in ('fit', 'control', 'cpu') and not args.part:
        parser.error('part is required')
    freeze() if args.stage == 'freeze' else run(args.stage, args.part)
