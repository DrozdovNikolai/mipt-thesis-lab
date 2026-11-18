"""Host runner for the frozen v15 experiment. No downloads or serving changes."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from scripts.soteria_training_v15 import POLICY, prepare, read, sha, save

WORKSPACE = Path(__file__).resolve().parents[1]
STUDY = WORKSPACE/'reports/soteria-training-v15'
IMAGE = 'north55-speech-train:publisher-v2'


def run(stage, arm=None):
    plan = read(STUDY/'plan.json')
    for name, expected in plan['code'].items():
        assert sha(STUDY/'frozen'/name) == expected, name
    for name, expected in plan['sources'].items():
        assert sha(WORKSPACE/name) == expected, name
    label = stage + ('-'+arm if arm else '')
    completion = STUDY/f'run-{label}.json'
    if completion.exists():
        assert read(completion)['exit_code'] == 0
        print('Already completed', label, flush=True)
        return
    runtime_fix = read(STUDY/'inference-runtime-fix.json') if (STUDY/'inference-runtime-fix.json').exists() and stage=='infer' else None
    name = 'north55-soteria-training-v15-'+label+('-runtimefix1' if runtime_fix else '')
    command = ['docker','run','--name',name,'--network','none','--entrypoint','python',
        '-e','PYTHONPATH=/app/src:/app','-e','HF_HUB_OFFLINE=1','-e','TRANSFORMERS_OFFLINE=1',
        '-e','CUDA_VISIBLE_DEVICES=0','-e','PYTHONDONTWRITEBYTECODE=1',
        '-e','LD_LIBRARY_PATH=/opt/venv/lib/python3.11/site-packages/nvidia/cublas/lib:/opt/venv/lib/python3.11/site-packages/nvidia/cudnn/lib',
        '-w','/app']
    def mount(source, target, readonly=True, volume=False):
        command.extend(['--mount', f'type={"volume" if volume else "bind"},source={str(source).replace(chr(92), "/")},target={target}' + (',readonly' if readonly else '')])
    mount(STUDY/'frozen','/app')
    mount(STUDY,'/study',False)
    mount('north55-speech_model_cache','/models',volume=True)
    if runtime_fix:
        assert sha(STUDY/'runtime/soteria_training_v15.py') == runtime_fix['runtime_sha256']
        assert sha(STUDY/'frozen/scripts/soteria_training_v15.py') == runtime_fix['original_sha256']
        assert sha(STUDY/'plan.json') == runtime_fix['original_plan_sha256']
        mount(STUDY/'runtime/soteria_training_v15.py','/runtime.py')
    if stage != 'score':
        # No human or weak evaluation reference text is visible inside training/inference.
        command += ['--tmpfs','/study/scoring:ro,mode=0555']
    if stage == 'train':
        mount('north55-speech_audio_data','/legacy',volume=True)
        mount(WORKSPACE/'data/curated/soteria-v14/audio','/soteria')
    if stage == 'infer':
        mount(WORKSPACE/'reports/cockpit-reviewed-v12/audio','/human')
        mount(WORKSPACE/'data/curated/soteria-v14/audio','/soteria')
    if stage in ('train','infer'):
        command += ['--gpus','device=0']
    if stage == 'tests':
        command += [IMAGE,'-m','pytest','tests/test_soteria_training_v15.py','-q','-p','no:cacheprovider']
    else:
        command += [IMAGE,'-u'] + (['/runtime.py'] if runtime_fix else ['-m','scripts.soteria_training_v15']) + [stage]
        if arm:
            command += ['--arm',arm]
    print('Starting', label, flush=True)
    result = subprocess.run(command, check=False)
    info = json.loads(subprocess.check_output(['docker','inspect',name]))[0]
    log = subprocess.check_output(['docker','logs',name],stderr=subprocess.STDOUT)
    log_name = f'run-{label}'+('-runtimefix1' if runtime_fix else '')+'.log'
    (STUDY/log_name).write_bytes(log)
    metadata = {'exit_code': result.returncode, 'image': info['Image'], 'state': info['State'],
                'network': info['HostConfig']['NetworkMode'], 'devices': info['HostConfig']['DeviceRequests'],
                'mounts': info['Mounts'], 'command': info['Config']['Cmd'], 'log':log_name,
                'runtime_fix':runtime_fix}
    if result.returncode:
        save(STUDY/f'failed-{label}.json',metadata)
        raise SystemExit(result.returncode)
    save(completion,metadata)
    subprocess.run(['docker','rm',name],check=True,stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','tests','train','convert','infer','score','all'])
    parser.add_argument('--arm',choices=POLICY['arms']+['small','large'])
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare(WORKSPACE)
    elif args.stage == 'all':
        if not (STUDY/'plan.json').exists():
            prepare(WORKSPACE)
        for stage in ('tests','train','convert'):
            run(stage)
        for arm in ['small','large']+POLICY['arms']:
            run('infer',arm)
        run('score')
    else:
        if args.stage == 'infer' and not args.arm:
            parser.error('--arm required')
        run(args.stage,args.arm)
