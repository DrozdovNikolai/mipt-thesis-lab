"""Exploratory known-English diagnostic; never changes serving models or gold."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.asr import AsrProvider
from north55_speech.core import file_hash
from north55_speech.schemas import PipelineConfig

ROOT = Path('/audit')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_new(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def infer():
    plan = read(ROOT / 'plan.json')
    if list((ROOT / 'predictions').glob('*.json')):
        raise ValueError('Existing diagnostic predictions are immutable')
    config = PipelineConfig.model_validate(plan['config'])
    provider = AsrProvider(config)
    assert provider.model.model.device == 'cuda'
    assert provider.model.model.compute_type == 'float16'
    assert provider.manifest == plan['model']['manifest']
    runtime = {
        'python': platform.python_version(),
        'packages': {n: importlib.metadata.version(n) for n in
                     ('faster-whisper', 'ctranslate2', 'numpy', 'soundfile', 'jiwer')},
        'device': provider.model.model.device,
        'precision': provider.model.model.compute_type,
        'plan_sha256': file_hash(ROOT / 'plan.json'),
        'script_sha256': file_hash(Path(__file__)),
        'asr_source_sha256': file_hash(Path('/source/north55_speech/asr.py')),
        'effective_options': {lang: provider.options(lang) for lang in plan['trials']},
    }
    write_new(ROOT / 'runtime.json', runtime)
    for item in plan['items']:
        audio_path = Path('/audio') / item['audio_path']
        assert file_hash(audio_path) == item['audio_sha256']
        waveform, rate = sf.read(audio_path, dtype='float32')
        assert rate == 16000 and waveform.ndim == 1 and np.isfinite(waveform).all()
        for language in plan['trials']:
            started = time.perf_counter()
            result = {'id': item['id'], 'group_id': item['group_id'],
                      'language': language, 'hypothesis': '', 'segments': [],
                      'runtime_failure': None, 'audio_sha256': item['audio_sha256'],
                      'plan_sha256': runtime['plan_sha256']}
            try:
                segments = provider.transcribe(waveform, 0, language, item['id'], lambda: None)
                result.update(hypothesis=' '.join(s.raw_asr_text.strip() for s in segments),
                              segments=[s.model_dump() for s in segments])
            except Exception as error:
                result['runtime_failure'] = {'type': type(error).__name__, 'message': str(error)}
            result['elapsed_sec'] = time.perf_counter() - started
            write_new(ROOT / 'predictions' / f'{language}-{item["id"]}.json', result)
            print(json.dumps({'id': item['id'], 'language': language,
                              'failure': result['runtime_failure'],
                              'elapsed_sec': result['elapsed_sec']}), flush=True)
    write_new(ROOT / 'execution.json', {
        'prediction_sha256': {p.name: file_hash(p) for p in sorted((ROOT / 'predictions').glob('*.json'))},
        'plan_sha256': runtime['plan_sha256'],
    })


def score():
    from north55_speech.metrics import corpus_counts, edit_counts

    plan, execution = read(ROOT / 'plan.json'), read(ROOT / 'execution.json')
    references_path = Path('/references.json')
    assert file_hash(references_path) == plan['references_sha256']
    references = read(references_path)
    assert execution['plan_sha256'] == file_hash(ROOT / 'plan.json')
    assert len(execution['prediction_sha256']) == len(plan['items']) * len(plan['trials'])
    rows = []
    for item in plan['items']:
        for language in plan['trials']:
            path = ROOT / 'predictions' / f'{language}-{item["id"]}.json'
            assert file_hash(path) == execution['prediction_sha256'][path.name]
            result = read(path)
            assert result['plan_sha256'] == execution['plan_sha256']
            result['reference'] = references[item['id']]
            result['counts'] = edit_counts(result['reference'], result['hypothesis'])
            rows.append(result)
    summaries = {lang: corpus_counts([r['counts'] for r in rows if r['language'] == lang])
                 for lang in plan['trials']}
    result = {'kind': 'exploratory_known_english_diagnostic', 'summaries': summaries,
              'groups': len({i['group_id'] for i in plan['items']}), 'items': len(plan['items']),
              'rows': rows, 'quality_evidence': False, 'release_promoted': False,
              'limitations': plan['limitations']}
    write_new(ROOT / 'comparison.json', result)
    print(json.dumps({'summaries': summaries, 'groups': result['groups'], 'items': result['items']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['infer', 'score'])
    args = parser.parse_args()
    infer() if args.mode == 'infer' else score()
