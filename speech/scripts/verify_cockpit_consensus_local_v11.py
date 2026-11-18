"""Verify the complete PowerShell/Docker pipeline, including newly generated Canary tokens."""
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    reports = Path(__file__).resolve().parents[1]/'reports'
    root = reports/'cockpit-consensus-v11/local-runtime'
    expected, actual = read(root/'smoke-expected.json'), read(root/'output/smoke.json')
    assert actual['runtime_sha256'] == sha(root/'runtime.json')
    assert actual['base_file_sha256'] == sha(root/'output/smoke-base.json')
    rows = {Path(r['input_path']).name: r for r in actual['records']}
    assert len(rows) == len(expected) == 6
    checked = []
    for item in expected:
        row = rows[item['file']]
        assert row['input_sha256'] == item['input_sha256'] == sha(root/'smoke-audio'/item['file'])
        assert row['pcm_sha256'] == item['pcm_sha256']
        assert row['base'] == item['base'] and row['hypothesis'] == item['hypothesis']
        assert row['accepted_edits'] == item['accepted_edits']
        if row['canary'] is not None:
            old = read(reports/'cockpit-candidates-v10/io-canary/predictions'/(item['id']+'.json'))
            assert row['canary']['hypothesis'] == old['hypothesis']
            assert row['canary']['token_ids'] == old['token_ids']
        checked.append({'file': item['file'], 'same_final_text_and_edits': True,
            'fresh_canary_tokens_checked': row['canary'] is not None})
    assert actual['actual_ASR_calls'] == {'whisper': 4, 'parakeet': 6, 'dfn_parakeet': 0, 'canary': 4}
    result = {'status': 'PASS', 'runtime_sha256': sha(root/'runtime.json'),
        'output_sha256': sha(root/'output/smoke.json'), 'new_GPU_ASR_calls': 14, 'cases': checked,
        'historical_parakeet_difference': 'See v10 local verification; all English inputs receive a separate batch-one audit',
        'independent_accuracy_evidence': False}
    with (root/'verification.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
