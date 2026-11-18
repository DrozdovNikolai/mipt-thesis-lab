"""Post-run fitting audit. Never changes references, training pairs or hypotheses."""

import json
from collections import Counter
from pathlib import Path

import numpy as np

from north55_speech.audio import RATE, VadProvider
from north55_speech.core import atomic_json, file_hash
from north55_speech.metrics import canonical_normalizer_v1, corpus_counts, edit_counts
from north55_speech.schemas import VadConfig
from scripts.decoding_diagnostics import load_audio

ROOT = Path('/study')
OUT = Path('/output')


def read(path):
    return json.loads(path.read_bytes())


def main():
    plan = read(ROOT / 'plan.json')
    if file_hash(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Frozen fitting inputs changed')
    refpath = ROOT / 'scoring/fit-references.json'
    if file_hash(refpath) != plan['scoring_sha256']['fit-references.json']:
        raise ValueError('Source references changed')
    refs = read(refpath)
    items = read(ROOT / 'inputs.json')['fit']
    records = {}
    for system in ('parent_on', 'nus_on'):
        folder = ROOT / ('fit-' + system)
        execution = read(folder / 'execution.json')
        if execution['plan_sha256'] != file_hash(ROOT / 'plan.json'):
            raise ValueError('Execution changed')
        records[system] = {}
        for item in items:
            path = folder / 'predictions' / (item['id'] + '.json')
            if file_hash(path) != execution['prediction_sha256'][path.name]:
                raise ValueError('Prediction changed')
            record = read(path)
            if record['runtime_failure'] is not None:
                raise ValueError('Fitting diagnosis contains a runtime failure')
            records[system][item['id']] = record
    vad_config = VadConfig(enabled=True, threshold=.4, min_speech_duration_ms=50,
                           min_silence_duration_ms=400, speech_pad_ms=0, max_speech_duration_s=30.)
    details, changes = [], Counter()
    lexical, canonical = {s: [] for s in records}, {s: [] for s in records}
    for item in items:
        key = item['id']
        values = {}
        for system in records:
            text = records[system][key]['hypothesis']
            score = edit_counts(refs[key], text)
            lexical[system].append(score)
            secondary = edit_counts(canonical_normalizer_v1(refs[key]), canonical_normalizer_v1(text))
            canonical[system].append(secondary)
            values[system] = {'hypothesis': text, 'score': score, 'secondary_canonical_score': secondary,
                              'decoder_calls': len(records[system][key]['trace'])}
        old, new = (sum(values[s]['score'][k] for k in ('S', 'D', 'I')) for s in ('parent_on', 'nus_on'))
        changes['better' if new < old else 'worse' if new > old else 'same'] += 1
        audio = load_audio(item)
        # Finalize VAD at EOF; padding is for inspection only, never ASR/training.
        padded = np.concatenate([audio, np.zeros(RATE, dtype='float32')])
        intervals = [(a, min(b, len(audio))) for a, b in VadProvider().intervals(padded, vad_config) if a < len(audio)]
        details.append({'id': key, 'audio_sha256': item['audio_sha256'], 'reference': refs[key],
                        'duration_sec': item['duration_sec'], 'lexical_error_delta': new-old,
                        'peak': float(np.abs(audio).max()), 'rms': float(np.sqrt(np.mean(audio.astype('float64')**2))),
                        'clipping_fraction': float(np.mean(np.abs(audio) >= .999)),
                        'vad_intervals_samples': intervals, 'vad_speech_sec': sum(b-a for a,b in intervals)/RATE,
                        'systems': values})
    result = {'status': 'EXECUTED_DIAGNOSTIC', 'script_sha256': file_hash(Path(__file__)),
              'plan_sha256': file_hash(ROOT / 'plan.json'), 'inputs': len(items), 'error_changes': dict(changes),
              'lexical': {s: corpus_counts(v) for s, v in lexical.items()},
              'secondary_canonical_not_primary_WER': {s: corpus_counts(v) for s, v in canonical.items()},
              'zero_error_clips': {s: sum(sum(v[k] for k in ('S', 'D', 'I')) == 0 for v in scores) for s,scores in lexical.items()},
              'decode_call_distribution': {s: dict(Counter(len(v['trace']) for v in rec.values())) for s,rec in records.items()},
              'vad': {'config': vad_config.model_dump(), 'zero_detected_speech': [v['id'] for v in details if v['vad_speech_sec'] == 0],
                      'meaning': 'Model screening only; VAD absence is not proof of absent speech. No exclusions.'},
              'zero_signal': [v['id'] for v in details if v['peak'] == 0],
              'audio_scope_verified': False, 'references_changed': False, 'pairs_excluded': 0,
              'new_ASR_calls': 0, 'quality_evidence': False, 'release_promoted': False}
    atomic_json(OUT / 'details.json', details)
    result['details_sha256'] = file_hash(OUT / 'details.json')
    atomic_json(OUT / 'summary.json', result)
    print(json.dumps({k: result[k] for k in ('inputs', 'error_changes', 'zero_error_clips', 'vad', 'zero_signal')}))


if __name__ == '__main__':
    main()
