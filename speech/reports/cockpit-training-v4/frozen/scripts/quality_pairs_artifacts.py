"""Cross-platform Docker commands for support import and artifact verification."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'reports/pair-quality-v1'
NAMES = [f'north55-quality-pairs-{stage}-v1' for stage in ('prepare', 'small', 'large', 'assemble', 'tests')]
NAMES += ['north55-quality-pairs-contracts-v2', 'north55-quality-pairs-contracts-v3', 'north55-training-support-import-v1']


def snapshot():
    for name in NAMES:
        raw = subprocess.check_output(['docker', 'inspect', name])
        info = json.loads(raw)[0]
        value = {'name': name, 'image_id': info['Image'], 'network_mode': info['HostConfig']['NetworkMode'],
                 'command': info['Config']['Cmd'], 'state': info['State'],
                 'mounts': [{key: m[key] for key in ('Type', 'Source', 'Destination', 'RW')} for m in info['Mounts']]}
        (STUDY / f'{name}.json').write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
        log = subprocess.run(['docker', 'logs', name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout
        (STUDY / f'{name}.log').write_bytes(log)
    print(f'Saved {len(NAMES)} container snapshots without environment credentials')


def run(action, resume):
    name = 'north55-training-support-import-v1' if action == 'import' else 'north55-quality-pairs-verification-v1'
    existing = subprocess.check_output(['docker', 'ps', '-a', '--filter', f'name=^/{name}$', '--format', '{{.Names}}'], text=True).strip()
    if existing:
        if not resume:
            raise ValueError(f'{name} exists; use --resume to intentionally verify/replay it')
        command = ['docker', 'start', '-a', name]
    else:
        mounts = [(ROOT/'scripts', '/app/scripts:ro'), (ROOT/'src', '/app/src:ro'), (STUDY, '/study'),
                  (ROOT/'data/curated/training-support-v1', '/prepared' + (':ro' if action == 'verify' else ''))]
        if action == 'import':
            mounts += [(ROOT/'data/input/pair-quality-sources-v1', '/support:ro'),
                       (ROOT/'data/curated/clean-controls-v1/plan.json', '/clean-plan.json:ro'),
                       (ROOT/'data/curated/additional-audio-v1/plan.json', '/additional-plan.json:ro'),
                       (ROOT/'data/input/fleurs-ru-v1/dev.tsv', '/fleurs-dev.tsv:ro')]
            image, module = 'north55-speech-train:publisher-v2', 'scripts.import_training_support'
        else:
            mounts += [(ROOT/'data/curated/pair-quality-v1', '/pairs:ro'),
                       (ROOT/'data/curated/publisher-expanded-v1', '/old:ro'),
                       (ROOT/'reports/language-large-v1/inputs.json', '/diagnostic-inputs.json:ro'),
                       (ROOT, '/workspace:ro')]
            image, module = 'north55-speech-gpu:0.1.0', 'scripts.verify_quality_pairs'
        command = ['docker', 'run', '--name', name, '--network', 'none', '--entrypoint', 'python']
        for source, destination in mounts:
            command += ['-v', f'{source}:{destination}']
        command += ['-v', 'north55-speech_audio_data:/audio' + (':ro' if action == 'verify' else ''), image, '-m', module]
    subprocess.run(command, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'import', 'verify', 'report'])
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.action == 'snapshot':
        snapshot()
    elif args.action == 'report':
        subprocess.run([sys.executable, str(ROOT/'scripts/report_quality_pairs.py')], check=True)
    else:
        run(args.action, args.resume)
