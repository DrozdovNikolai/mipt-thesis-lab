"""Freeze a runnable consensus stage and six audio-only regression cases."""
import os
import shutil
from pathlib import Path

from package_cockpit_hybrid_v10 import read, save

from north55_speech.core import file_hash


def main():
    work, package = Path('/workspace'), Path('/package')
    study = work/'reports/cockpit-consensus-v11'
    prior = work/'reports/cockpit-candidates-v10'
    assert read(study/'verification.json')['status'] == 'PASS'
    assert read(study/'comparison.json')['diagnostic_pass']['edits']
    assert read(prior/'local-runtime/verification.json')['status'] == 'PASS'
    assert not (package/'runtime.json').exists()
    frozen = package/'frozen'
    shutil.copytree(prior/'local-runtime/frozen', frozen)
    for name in ('src/north55_speech/cockpit_consensus_v11.py', 'scripts/transcribe_cockpit_consensus_v11.py'):
        shutil.copyfile(work/name, frozen/name)
    config = {'implementation_sha256': {p.relative_to(frozen).as_posix(): file_hash(p)
        for p in sorted(frozen.rglob('*.py'))}, 'base_runtime_sha256': file_hash(prior/'local-runtime/runtime.json'),
        'v11_plan_sha256': file_hash(study/'plan.json'), 'comparison_sha256': file_hash(study/'comparison.json'),
        'models': read(prior/'model-manifest.json'), 'experimental': True,
        'smoke_rule': 'v10 five cases plus first sorted train id with accepted consensus edit, irrespective of correctness'}
    save(package/'runtime.json', config)
    rows = {r['id']: r for r in read(study/'io-infer/decisions.json')}
    items = {i['id']: i for i in read(prior/'inputs.json')}
    cases = [(r['file'], r['id']) for r in read(prior/'local-runtime/smoke-expected.json')]
    extra = sorted(k for k, r in rows.items() if k.startswith('fit-') and r['accepted_edits'])[0]
    cases.append(('consensus-edit.wav', extra))
    expected = []
    for filename, identity in cases:
        item, row = items[identity], rows[identity]
        source = Path('/cross')/item['audio_path']
        assert file_hash(source) == item['audio_sha256']
        target = package/'smoke-audio'/filename
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        expected.append({'file': filename, 'id': identity, 'input_sha256': item['audio_sha256'],
            'pcm_sha256': item['pcm_sha256'], 'base': row['base'], 'hypothesis': row['edits'],
            'accepted_edits': row['accepted_edits'], 'parakeet': item['parakeet'], 'whisper': item['whisper']})
    save(package/'smoke-expected.json', expected)
    (package/'output').mkdir()
    for p in [package, *package.rglob('*')]:
        os.chown(p, 10001, 10001)
    print({'runtime_sha256': file_hash(package/'runtime.json'), 'smoke_files': len(expected)}, flush=True)


if __name__ == '__main__':
    main()
