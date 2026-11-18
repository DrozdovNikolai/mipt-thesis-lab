"""Replay two fixed inference cases in a new model process without references."""
import json
from pathlib import Path

from cockpit_candidates_v10 import ROOT, read, validate, validate_models, waveform

from north55_speech.cockpit_candidates_v10 import load_canary, transcribe_canary
from north55_speech.core import file_hash


def main():
    validate()
    manifest = validate_models()
    inputs = [i for i in read(ROOT/'inputs.json') if i['language'] == 'en']
    selected = [inputs[0], max(inputs, key=lambda i: i['duration_sec'])]
    model = load_canary(manifest['models'][0]['snapshot'])
    rows = []
    for item in selected:
        actual = transcribe_canary(model, waveform(item))
        expected = read(Path('/predictions')/(item['id']+'.json'))
        assert expected['item'] == item and expected['plan_sha256'] == file_hash(ROOT/'plan.json')
        for key in ('hypothesis', 'token_ids', 'eos_reached', 'token_limit_reached'):
            assert actual[key] == expected[key], (item['id'], key)
        rows.append({'id': item['id'], 'duration_sec': item['duration_sec'],
            'text_and_token_ids_exact': True})
    result = {'status': 'PASS', 'new_GPU_ASR_calls': 2, 'plan_sha256': file_hash(ROOT/'plan.json'),
        'selection': 'first English input and longest English input in frozen manifest', 'cases': rows,
        'code_sha256': file_hash(Path(__file__))}
    with Path('/output/canary-replay.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(result, flush=True)


if __name__ == '__main__':
    main()
