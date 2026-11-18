"""Offline, reference-blind NUS fitting and decoder-context diagnosis.

Run through run_nus_failure_diagnosis.py. These are exposed development and
training observations, never a final test or a release-selection protocol.
"""

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import time
from contextlib import contextmanager
from pathlib import Path

from north55_speech.asr import AsrProvider
from north55_speech.core import atomic_json, file_hash, now
from north55_speech.schemas import PipelineConfig
from scripts.decoding_diagnostics import load_audio, read

ROOT = Path('/study')


@contextmanager
def trace_decoder(model):
    """Record actual backend calls without changing audio, prompts or tokens.

    Used in a single-request experiment process only, never a shared server.
    Restore every hook even if transcription raises or its generator is closed.
    """
    names = ('get_prompt', 'generate_with_fallback', '_split_segments_by_timestamps', 'add_word_timestamps')
    originals = {name: getattr(model, name) for name in names}
    calls, pending = [], {}

    def prompt(*args, **kwargs):
        values = inspect.signature(originals['get_prompt']).bind(*args, **kwargs).arguments
        result = originals['get_prompt'](*args, **kwargs)
        pending['previous_token_count'] = len(values['previous_tokens'])
        pending['prompt_token_ids'] = list(result)
        return result

    def generate(*args, **kwargs):
        values = inspect.signature(originals['generate_with_fallback']).bind(*args, **kwargs).arguments
        result = originals['generate_with_fallback'](*args, **kwargs)
        decoded, logprob, temperature, compression = result
        tokens = list(decoded.sequences_ids[0])
        calls.append({**pending, 'index': len(calls), 'decoded_token_ids': tokens,
                      'decoded_text': values['tokenizer'].decode(tokens),
                      'avg_logprob': float(logprob), 'temperature': float(temperature),
                      'compression_ratio': float(compression), 'no_speech_prob': float(decoded.no_speech_prob)})
        return result

    def split(*args, **kwargs):
        values = inspect.signature(originals['_split_segments_by_timestamps']).bind(*args, **kwargs).arguments
        result = originals['_split_segments_by_timestamps'](*args, **kwargs)
        segments, seek, single_end = result
        calls[-1].update(input_seek_frames=values['seek'], time_offset_sec=values['time_offset'],
                         segment_duration_sec=values['segment_duration'], seek_after_split_frames=seek,
                         single_timestamp_ending=single_end,
                         split_segments=[{'start': s['start'], 'end': s['end'],
                                          'text': values['tokenizer'].decode(s['tokens'])} for s in segments])
        return result

    def align(*args, **kwargs):
        values = inspect.signature(originals['add_word_timestamps']).bind(*args, **kwargs).arguments
        result = originals['add_word_timestamps'](*args, **kwargs)
        calls[-1]['aligned_segments'] = [dict(s) for batch in values['segments'] for s in batch]
        return result

    try:
        for name, callback in zip(names, (prompt, generate, split, align), strict=True):
            setattr(model, name, callback)
        yield calls
    finally:
        for name, callback in originals.items():
            setattr(model, name, callback)


def validate():
    plan = read(ROOT / 'plan.json')
    for filename, expected in plan['implementation_sha256'].items():
        if file_hash(Path('/app') / filename) != expected:
            raise ValueError('Frozen source/contract changed: ' + filename)
    if file_hash(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Inputs changed')
    if file_hash(ROOT / 'protocol.md') != plan['protocol_sha256']:
        raise ValueError('Protocol changed')
    for value in plan['models'].values():
        if file_hash(Path('/models') / value['name'] / 'manifest.json') != value['manifest_sha256']:
            raise ValueError('Model identity changed')
    return plan


def infer(stage, system, cpu=False):
    plan = validate()
    config = PipelineConfig.model_validate(plan['configs'][system])
    if cpu:
        config = config.model_copy(update={'device': 'cpu', 'compute_type': 'int8'})
    items = read(ROOT / 'inputs.json')[stage]
    if cpu:
        items = [items[0]]
    name = ('cpu-' if cpu else '') + stage + '-' + system
    output = ROOT / name
    output.mkdir(exist_ok=True)
    attempt = now().strftime('%Y%m%dT%H%M%S%fZ')
    runtime = {'plan_sha256': file_hash(ROOT / 'plan.json'), 'new_records': 0, 'resumed_records': 0,
               'started_at': now().isoformat(), 'packages': {p: importlib.metadata.version(p) for p in
               ('faster-whisper', 'ctranslate2', 'numpy', 'soundfile')}, 'status': 'RUNNING'}
    started = time.perf_counter()
    try:
        provider = AsrProvider(config)
        runtime.update(actual_device=provider.model.model.device, actual_precision=provider.model.model.compute_type,
                       backend_loop_sha256=hashlib.sha256(inspect.getsource(type(provider.model).generate_segments).encode()).hexdigest())
        if not cpu and (runtime['actual_device'], runtime['actual_precision']) != ('cuda', 'float16'):
            raise ValueError('Unexpected inference precision/device')
        for index, item in enumerate(items):
            path = output / 'predictions' / (item['id'] + '.json')
            options = provider.options(item['input_language'])
            if path.exists():
                previous = read(path)
                if (previous['plan_sha256'] != runtime['plan_sha256'] or previous['config'] != config.model_dump()
                        or previous['effective_options'] != options or any(previous[k] != v for k, v in item.items())
                        or previous['runtime_failure'] is not None):
                    raise ValueError('Resume differs or contains a failed record; preserve and audit a new attempt')
                runtime['resumed_records'] += 1
                continue
            record = {**item, 'plan_sha256': runtime['plan_sha256'], 'system': system,
                      'config': config.model_dump(), 'effective_options': options,
                      'runtime_failure': None, 'hypothesis': '', 'segments': [], 'trace': []}
            begin = time.perf_counter()
            try:
                waveform = load_audio(item)
                record['effective_waveform_sha256'] = hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest()
                with trace_decoder(provider.model) as trace:
                    segments = provider.transcribe(waveform, 0, item['input_language'], item['id'], lambda: None)
                record.update(hypothesis=' '.join(s.raw_asr_text.strip() for s in segments),
                              segments=[s.model_dump() for s in segments], trace=trace)
            except Exception as exc:
                record['runtime_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            record['elapsed_sec'] = time.perf_counter() - begin
            atomic_json(path, record)
            runtime['new_records'] += 1
            if index % 25 == 0 or index + 1 == len(items):
                print(json.dumps({'stage': stage, 'system': system, 'completed': index + 1, 'total': len(items),
                                  'runtime_failure': record['runtime_failure']}), flush=True)
        runtime['status'] = 'COMPLETED'
    except Exception as exc:
        runtime.update(status='FAILED', error=repr(exc))
        raise
    finally:
        runtime.update(finished_at=now().isoformat(), elapsed_sec=time.perf_counter() - started)
        atomic_json(output / ('runtime-' + attempt + '.json'), runtime)
    hashes = {p.name: file_hash(p) for p in (output / 'predictions').glob('*.json')}
    if set(hashes) != {i['id'] + '.json' for i in items}:
        raise ValueError('Incomplete/unexpected prediction population')
    atomic_json(output / 'execution.json', {'plan_sha256': runtime['plan_sha256'], 'prediction_sha256': hashes,
                'runtime_sha256': {p.name: file_hash(p) for p in output.glob('runtime-*.json')}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('trace', 'fit', 'context'))
    parser.add_argument('system', choices=('parent_on', 'parent_off', 'nus_on', 'nus_off'))
    parser.add_argument('--cpu', action='store_true')
    args = parser.parse_args()
    infer(args.stage, args.system, args.cpu)
