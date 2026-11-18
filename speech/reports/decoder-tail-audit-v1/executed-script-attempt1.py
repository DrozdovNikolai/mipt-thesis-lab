"""Trace an unchanged diagnostic request; no new tuning or reference access."""

import hashlib
import inspect
import json
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.schemas import PipelineConfig
from scripts.decoding_diagnostics import DiagnosticProvider, load_audio, read


def main():
    plan = read(Path('/study/plan.json'))
    item = next(i for i in read(Path('/study/inputs.json')) if i['id'] == '3536-8226-0027')
    result = {'kind': 'instrumented replay of already executed configurations',
              'new_configurations': 0, 'training_runs': 0, 'references_accessed': False,
              'input_id': item['id'], 'audio_sha256': item['audio_sha256'],
              'plan_sha256': file_hash(Path('/study/plan.json')), 'runs': {}}
    for mode in ('baseline', 'text'):
        config = PipelineConfig.model_validate(plan['configs']['parent_' + mode])
        provider = DiagnosticProvider(config, without_timestamps=mode == 'text')
        model = provider.model
        # load_model caches this object; restore wrappers after each run.
        original_split = model._split_segments_by_timestamps
        original_align = model.add_word_timestamps
        trace = []

        def split(*args, **kwargs):
            values = inspect.signature(original_split).bind(*args, **kwargs).arguments
            segments, seek, single_ending = original_split(*args, **kwargs)
            trace.append({'input_seek_frames': values['seek'],
                          'time_offset_sec': values['time_offset'],
                          'segment_duration_sec': values['segment_duration'],
                          'seek_after_token_split_frames': seek,
                          'single_timestamp_ending': single_ending,
                          'decoded_text': ' '.join(values['tokenizer'].decode(s['tokens']) for s in segments)})
            return segments, seek, single_ending

        def align(*args, **kwargs):
            values = inspect.signature(original_align).bind(*args, **kwargs).arguments
            returned = original_align(*args, **kwargs)
            words = [w for s in values['segments'] for w in s.get('words', [])]
            trace[-1]['last_aligned_word_end_sec'] = words[-1]['end'] if words else None
            return returned

        model._split_segments_by_timestamps = split
        model.add_word_timestamps = align
        try:
            segments = provider.transcribe(load_audio(item), 0, item['input_language'], item['id'], lambda: None)
        finally:
            model._split_segments_by_timestamps = original_split
            model.add_word_timestamps = original_align
        result['runs'][mode] = {'effective_options': provider.options(item['input_language']),
                               'actual_precision': model.model.compute_type,
                               'trace': trace, 'segments': [s.model_dump() for s in segments],
                               'hypothesis': ' '.join(s.raw_asr_text.strip() for s in segments)}
        source = inspect.getsource(type(model).generate_segments)
        result['backend_generate_segments_sha256'] = hashlib.sha256(source.encode()).hexdigest()
    atomic_json(Path('/output/trace.json'), result)
    print(json.dumps({m: {'decode_windows': len(r['trace']), 'hypothesis': r['hypothesis']} for m, r in result['runs'].items()}))


if __name__ == '__main__':
    main()
