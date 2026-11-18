"""Package an evaluated v10 variant and audio-only cases for fresh ASR verification."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from north55_speech.core import file_hash


def read(path):
    return json.loads(path.read_bytes())


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', choices=['guarded_v9', 'dfn_parakeet'])
    candidate = parser.parse_args().candidate
    work = Path('/workspace')
    prior = work/'reports/cockpit-noise-router-v9'
    study = work/'reports/cockpit-candidates-v10'
    root = Path('/package')
    assert read(study/'verification.json')['status'] == 'PASS'
    assert not (root/'runtime.json').exists()
    report = read(study/'comparison.json')
    if candidate == 'dfn_parakeet':
        assert report['diagnostic_pass'][candidate], 'Do not package a failed denoising variant as default'
    config = read(prior/'local-runtime/runtime.json')
    frozen = root/'frozen'
    shutil.copytree(prior/'local-runtime/frozen', frozen)
    for name in ('scripts/transcribe_cockpit_hybrid_v10.py', 'src/north55_speech/cockpit_candidates_v10.py'):
        shutil.copyfile(work/name, frozen/name)
    config['implementation_sha256'] = {p.relative_to(frozen).as_posix(): file_hash(p)
        for p in sorted(frozen.rglob('*.py'))}
    config.update({'candidate': candidate, 'v10_plan_sha256': file_hash(study/'plan.json'),
        'v10_comparison_sha256': file_hash(study/'comparison.json'),
        'deep_filter_binary_sha256': read(study/'model-manifest.json')['deep_filter_binary']['sha256'],
        'smoke_rule': 'v9 clean/noisy/empty/quiet plus train empty-decoder regression'})
    save(root/'runtime.json', config)
    expected = []
    rows = read(study/'composed-predictions.json')
    items = {i['id']: i for i in read(study/'inputs.json')}
    prior_cases = read(prior/'live-smoke-expected.json')
    cases = [(r['file'], r['id']) for r in prior_cases]
    cases.append(('empty-decoder-speech.wav', 'fit-269f4ee5cf035f4eb4ca0f9c62101119'))
    for name, identity in cases:
        item = items[identity]
        source = Path('/cross')/item['audio_path']
        assert file_hash(source) == item['audio_sha256']
        target = root/'smoke-audio'/name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        expected.append({'file': name, 'id': identity, 'pcm_sha256': item['pcm_sha256'],
            'input_sha256': item['audio_sha256'], 'hypothesis': rows[identity][candidate],
            'whisper': item['whisper'], 'parakeet': item['parakeet']})
    save(root/'smoke-expected.json', expected)
    (root/'output').mkdir(exist_ok=True)
    for path in [root, *root.rglob('*')]:
        os.chown(path, 10001, 10001)
    print({'candidate': candidate, 'runtime_sha256': file_hash(root/'runtime.json'), 'smoke_files': len(expected)})


if __name__ == '__main__':
    main()
