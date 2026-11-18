"""Check fresh local ASR against the audio and choices used by the routing study."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]/'reports/cockpit-noise-router-v9'
    expected = json.loads((root/'live-smoke-expected.json').read_bytes())
    output = json.loads((root/'local-output/smoke.json').read_bytes())
    runtime = root/'local-runtime/runtime.json'
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    assert output['runtime_sha256'] == digest(runtime)
    by_file = {Path(r['input_path']).name: r for r in output['records']}
    comparisons = []
    for item in expected:
        row = by_file[item['file']]
        assert row['input_sha256'] == digest(root/'smoke-audio'/item['file'])
        assert row['pcm_sha256'] == item['pcm_sha256']
        assert row['selected'] == item['route'] and row['hypothesis'] == item['hypothesis']
        emitted = [s for s in ('whisper', 'parakeet') if row[s] is not None]
        for system in emitted:
            assert row[system] == item[system]
        comparisons.append({'file': item['file'], 'same_waveform': True,
            'same_route': True, 'same_output_text': True, 'ASR_responses_matched': emitted})
    assert output['actual_ASR_calls'] == {'whisper': 2, 'parakeet': 4}
    result = {'status': 'PASS', 'new_GPU_ASR': 6, 'files': 4, 'comparisons': comparisons,
        'runtime_sha256': digest(runtime), 'output_sha256': digest(root/'local-output/smoke.json'),
        'interpretation': 'Fresh pipeline execution, not independent accuracy evidence'}
    target = root/'live-smoke-verification.json'
    if target.exists():
        assert json.loads(target.read_bytes()) == result
    else:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
