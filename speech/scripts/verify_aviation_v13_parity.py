"""Check the checkpoint driver against previously frozen end-to-end outputs."""
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    root = Path(__file__).resolve().parents[1]/'reports/aviation-v13'
    plan = read(root/'plan.json')
    assert hashlib.sha256((root/'scoring/parity.json').read_bytes()).hexdigest() == plan['parity_sha256']
    expected = read(root/'scoring/parity.json')
    for stage in ['hybrid', 'consensus']:
        actual = read(root/f'io-smoke/{stage}.json')
        assert len(actual['records']) == len(expected[stage]['records']) == 16
        assert actual['actual_ASR_calls'] == expected[stage]['actual_ASR_calls']
        for before, after in zip(expected[stage]['records'], actual['records'], strict=True):
            assert before == after, (stage, before['input_path'])
    report = {'status': 'PASS', 'identical_records': 32, 'new_ASR_calls': 48,
              'checks': ['all raw texts', 'word timestamps', 'PCM and file hashes', 'routing', 'consensus edits', 'Canary tokens']}
    target = root/'parity-verification.json'
    if target.exists():
        assert read(target) == report
    else:
        target.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
