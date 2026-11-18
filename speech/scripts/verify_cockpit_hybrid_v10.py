"""Verify local fresh ASR results against the frozen experiment."""
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    study = Path(__file__).resolve().parents[1]/'reports/cockpit-candidates-v10'
    root = study/'local-runtime'
    actual = read(root/'output/smoke.json')
    expected = read(root/'smoke-expected.json')
    assert actual['runtime_sha256'] == sha(root/'runtime.json')
    rows = {Path(r['input_path']).name: r for r in actual['records']}
    assert len(rows) == len(expected) == 5
    comparisons = []
    candidate_differences = []
    for item in expected:
        row = rows[item['file']]
        assert row['input_sha256'] == item['input_sha256'] == sha(root/'smoke-audio'/item['file'])
        assert row['pcm_sha256'] == item['pcm_sha256'] and row['hypothesis'] == item['hypothesis']
        for system in ('whisper', 'parakeet'):
            if row[system] is not None:
                if row[system] != item[system]:
                    assert system == 'parakeet' and row['selected'] != 'parakeet'
                    candidate_differences.append({'file': item['file'], 'system': system,
                        'cached': item[system], 'fresh': row[system], 'final_text_unchanged': True})
        if row['dfn_parakeet'] is not None:
            ref = read(study/'io-dfn/predictions'/(item['id']+'.json'))
            assert row['dfn_parakeet'] == ref['hypothesis']
            assert row['denoising']['pcm_sha256'] == ref['output_pcm_sha256']
        if item['file'] == 'empty-decoder-speech.wav':
            assert row['hypothesis'].strip()
        comparisons.append({'file': item['file'], 'same_input': True, 'same_output': True,
            'reason': row['reason']})
    expected_calls = {'whisper': 3, 'parakeet': 5, 'dfn_parakeet': int(actual['candidate'] == 'dfn_parakeet')}
    assert actual['actual_ASR_calls'] == expected_calls
    data = {'status': 'PASS', 'runtime_sha256': sha(root/'runtime.json'),
        'output_sha256': sha(root/'output/smoke.json'), 'files': comparisons,
        'unselected_candidate_differences': candidate_differences,
        'historical_empty_decoder_reproduced': rows['empty-decoder-speech.wav']['parakeet'] == '',
        'new_GPU_ASR_calls': expected_calls, 'independent_accuracy_evidence': False}
    with (root/'verification.json').open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(data, ensure_ascii=False))


if __name__ == '__main__':
    main()
