"""Second local stage: new Canary inference and two-model agreement edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from transcribe_cockpit_hybrid_v9 import load_wave, read

from north55_speech.cockpit_candidates_v10 import load_canary, transcribe_canary
from north55_speech.cockpit_consensus_v11 import select_consensus
from north55_speech.core import file_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output filename')
    config = read('/profile/runtime.json')
    for name, digest in config['implementation_sha256'].items():
        assert file_hash(Path('/app')/name) == digest
    base = read(args.base)
    assert base['candidate'] == 'guarded_v9'
    assert base['runtime_sha256'] == config['base_runtime_sha256']
    start, model, calls = time.perf_counter(), None, 0
    results = []
    for item in base['records']:
        source = Path(item['input_path']).resolve()
        assert source.is_relative_to(Path('/input')) and file_hash(source) == item['input_sha256']
        x = load_wave(source)
        assert hashlib.sha256(x.astype('<f4').tobytes()).hexdigest() == item['pcm_sha256']
        language = 'ru' if item['language_profile'] == 'ru' else 'en'
        severe = item['reason'] == 'severe_noise'
        needed = language == 'en' and not severe and bool(item['hypothesis'].strip()) and bool(item['parakeet'])
        canary = None
        if needed:
            if model is None:
                for info in config['models']['models']:
                    for name, expected in info['files'].items():
                        assert file_hash(Path(info['snapshot'])/name) == expected['sha256']
                model = load_canary(config['models']['models'][0]['snapshot'])
            canary = transcribe_canary(model, x)
            calls += 1
            if canary['token_limit_reached']:
                raise RuntimeError('Canary generation limit reached; preserve the base result for review')
        decision = select_consensus(item['hypothesis'], item['parakeet'],
            canary['hypothesis'] if canary else None, language, severe)
        changed = bool(decision['accepted_edits'])
        results.append({'input_path': item['input_path'], 'input_sha256': item['input_sha256'],
            'pcm_sha256': item['pcm_sha256'], 'duration_sec': item['duration_sec'],
            'base': item['hypothesis'], 'parakeet': item['parakeet'], 'canary': canary,
            'hypothesis': decision['edits'], 'accepted_edits': decision['accepted_edits'],
            'changed': changed, 'base_reason': item['reason'],
            'alignment_status': 'edited_words_not_aligned' if changed else 'base_timestamps_preserved',
            'base_word_timestamps_in': str(args.base), 'language_profile': item['language_profile']})
    output = {'runtime_sha256': file_hash(Path('/profile/runtime.json')), 'candidate': 'consensus_edits_v11',
        'base_file_sha256': file_hash(args.base), 'records': results,
        'actual_ASR_calls': {**base['actual_ASR_calls'], 'canary': calls},
        'second_stage_seconds': time.perf_counter()-start, 'experimental': True, 'serving_replaced': False}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'output': str(args.output), 'calls': output['actual_ASR_calls'],
        'results': [{'input': r['input_path'], 'text': r['hypothesis'], 'edits': r['accepted_edits']}
            for r in results]}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
