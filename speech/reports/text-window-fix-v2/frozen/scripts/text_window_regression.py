"""Real-audio regression with an engineered duplicate, no gold or prompts."""

import json
import re
from pathlib import Path

import numpy as np

from north55_speech.audio import RATE
from north55_speech.core import atomic_json, file_hash
from north55_speech.schemas import PipelineConfig
from scripts import decoding_diagnostics as d
from scripts.text_window_experiment import validate


def main():
    plan = validate()
    item = next(i for i in d.read(Path('/study/inputs.json')) if i['id'] == '3536-8226-0027')
    waveform = d.load_audio(item)
    provider = d.DiagnosticProvider(PipelineConfig.model_validate(plan['configs']['parent_text']), True)
    variants = {'original': waveform, 'repeated': np.concatenate([waveform, np.zeros(RATE, dtype='float32'), waveform]),
                'empty': np.zeros(0, dtype='float32')}
    results = {}
    for name, audio in variants.items():
        calls = []
        original_generate = provider.model.generate_with_fallback

        def generate(*args, _original=original_generate, _calls=calls, **kwargs):
            _calls.append(len(_calls))
            return _original(*args, **kwargs)

        provider.model.generate_with_fallback = generate
        try:
            # Engineered placement at +30s tests coordinate translation, not a
            # claim about where this standalone LibriSpeech clip was recorded.
            segments = provider.transcribe(audio, 30 * RATE, item['input_language'], name, lambda: None) if len(audio) else []
        finally:
            provider.model.generate_with_fallback = original_generate
        results[name] = {'decoder_calls': len(calls), 'duration_sec': len(audio) / RATE,
                         'hypothesis': ' '.join(s.raw_asr_text.strip() for s in segments),
                         'segments': [s.model_dump() for s in segments]}
    def tokens(value):
        return re.findall(r'\w+', value.casefold())
    checks = {'original_decoded_once': results['original']['decoder_calls'] == 1,
              'repeated_decodes_two_spoken_copies': results['repeated']['decoder_calls'] == 2,
              'empty_does_not_decode': results['empty']['decoder_calls'] == 0,
              'both_utterances_retained': tokens(results['repeated']['hypothesis']) == 2 * tokens(results['original']['hypothesis']),
              'nonempty_original_alignment': bool(results['original']['segments']) and all(s['words'] for s in results['original']['segments']),
              'translated_word_times_in_range': all(30 <= w['start_sec'] <= w['end_sec'] <= 30 + r['duration_sec'] + 1e-6
                  for r in results.values() for s in r['segments'] for w in s['words'])}
    output = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks, 'results': results,
              'plan_sha256': file_hash(Path('/study/plan.json')), 'source_audio_sha256': item['audio_sha256'],
              'actual_precision': provider.model.model.compute_type, 'quality_evidence': False,
              'note': 'Engineered audio repetition and coordinate regression; not independent speech or critical-command gold.'}
    atomic_json(Path('/study/regressions/result.json'), output)
    print(json.dumps({'status': output['status'], 'checks': checks, 'hypotheses': {k: v['hypothesis'] for k, v in results.items()}}))
    if output['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
