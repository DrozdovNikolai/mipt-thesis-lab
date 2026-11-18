"""Freeze and execute English ASR candidates without giving references to inference."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import time
from pathlib import Path

import soundfile as sf

from north55_speech.cockpit_candidates_v10 import (
    deep_filter,
    load_canary,
    speech_present,
    transcribe_canary,
)
from north55_speech.core import file_hash

ROOT, OUT = Path('/study'), Path('/output')
FILES = ['scripts/cockpit_candidates_v10.py', 'scripts/report_cockpit_candidates_v10.py',
    'src/north55_speech/cockpit_candidates_v10.py',
    'src/north55_speech/core.py', 'src/north55_speech/metrics.py',
    'src/north55_speech/__init__.py']


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def pcm(x):
    return hashlib.sha256(x.astype('<f4').tobytes()).hexdigest()


def prepare():
    work, prior = Path('/workspace'), Path('/workspace/reports/cockpit-noise-router-v9')
    assert not (ROOT/'plan.json').exists()
    p9 = read(prior/'plan.json')
    assert read(prior/'verification.json')['status'] == 'PASS'
    for name, key in [('inputs.json', 'inputs_sha256'), ('scoring/references.json', 'references_sha256')]:
        assert file_hash(prior/name) == p9[key]
        save(ROOT/name, read(prior/name))
    old_exec = read(prior/'io-infer/execution.json')
    assert file_hash(prior/'io-infer/decisions.json') == old_exec['decisions_sha256']
    save(ROOT/'prior-decisions.json', read(prior/'io-infer/decisions.json'))
    save(ROOT/'model-manifest.json', read(Path('/acquired/model-manifest.json')))
    frozen = ROOT/'frozen'
    for name in FILES:
        target = frozen/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work/name, target)
    severe = [r['id'] for r in read(ROOT/'prior-decisions.json')
        if r['selected'] == 'parakeet' and r['hypothesis'].strip()]
    assert len(severe) == 56
    plan = {'prior_plan_sha256': file_hash(prior/'plan.json'),
        'files_sha256': {name: file_hash(ROOT/name) for name in ('inputs.json',
            'scoring/references.json', 'prior-decisions.json', 'model-manifest.json', 'protocol.md')},
        'implementation_sha256': {n: file_hash(frozen/n) for n in FILES},
        'canary_revision': 'b1469e1bba1cfe140205529c79c434ca47180960',
        'canary_prompt': 'Transcribe the following: <|audioplaceholder|>',
        'canary_generation': {'do_sample': False, 'num_beams': 1, 'max_new_tokens': 256},
        'canary_audio_batch_size': 1, 'canary_autocast': 'bfloat16', 'seed': 55,
        'canary_weights_dtype': 'bfloat16', 'canary_mel_dtype': 'float32',
        'deep_filter': {'version': '0.5.6', 'attenuation_limit_db': 100,
            'post_filter': False, 'min_db_thresh': -15, 'max_db_erb_thresh': 35,
            'max_db_df_thresh': 35, 'flush_padding_48k': 48000, 'fresh_process_per_clip': True},
        'denoise_input_ids': severe, 'inputs': 541, 'english_inputs': 491,
        'planned_new_ASR_calls': {'canary': 491, 'dfn_parakeet': 56},
        'systems': ['v9', 'guarded_v9', 'canary', 'canary_guarded', 'canary_router', 'dfn_parakeet'],
        'VAD': {'threshold': .5, 'min_speech_duration_ms': 100,
            'min_silence_duration_ms': 400, 'speech_pad_ms': 200, 'max_speech_duration_s': 30},
        'blind_dev_accessed': False, 'test_accessed': False, 'ASR_training_updates': 0,
        'image': 'north55-speech-canary:v10',
        'image_id': os.environ['CANARY_IMAGE_ID'],
        'parakeet_image': 'north55-speech-parakeet:v6',
        'parakeet_image_id': 'sha256:47994dcc9e737b388bc6787b0a17da302f40d07c997aa3c1a9b2ace0c5f2d7ba'}
    save(ROOT/'plan.json', plan)
    for name in ('io-canary', 'io-dfn', 'scoring'):
        (ROOT/name).mkdir(exist_ok=True)
    for p in [ROOT, *ROOT.rglob('*')]:
        os.chown(p, 10001, 10001)
    print({'plan_sha256': file_hash(ROOT/'plan.json'), 'new_ASR_calls': 547}, flush=True)


def validate():
    plan = read(ROOT/'plan.json')
    for n, digest in plan['implementation_sha256'].items():
        assert file_hash(Path('/app')/n) == digest, n
    for n, digest in plan['files_sha256'].items():
        if n.startswith('scoring/'):
            continue
        assert file_hash(ROOT/n) == digest, n
    return plan


def waveform(item):
    p = (Path('/cross')/item['audio_path']).resolve()
    assert p.is_relative_to(Path('/cross/input-audio'))
    assert file_hash(p) == item['audio_sha256']
    x, rate = sf.read(p, dtype='float32')
    assert rate == 16000 and x.ndim == 1 and pcm(x) == item['pcm_sha256']
    return x


def validate_models():
    manifest = read(ROOT/'model-manifest.json')
    for model in manifest['models']:
        for name, meta in model['files'].items():
            p = Path(model['snapshot'])/name
            assert p.stat().st_size == meta['bytes'] and file_hash(p) == meta['sha256'], name
    assert file_hash(Path('/models/deep-filter')) == manifest['deep_filter_binary']['sha256']
    return manifest


def run(system):
    import torch
    start = time.perf_counter()
    plan = validate()
    manifest = validate_models()
    inputs = [i for i in read(ROOT/'inputs.json') if i['language'] == 'en'
        and (system == 'canary' or i['id'] in plan['denoise_input_ids'])]
    assert len(inputs) == plan['planned_new_ASR_calls'][system]
    assert not (OUT/'execution.json').exists()
    torch.set_num_threads(4)
    torch.manual_seed(55)
    if system == 'canary':
        model = load_canary(manifest['models'][0]['snapshot'])
    else:
        from nemo.collections.asr.models import ASRModel
        path = Path('/cross/parakeet/parakeet-tdt-0.6b-v2.nemo')
        assert file_hash(path) == 'd99e39955c9d3d0350d8fb7c75e40c64a2b2eaeb003883d7c941fd2e8747b28c'
        model = ASRModel.restore_from(str(path), map_location=torch.device('cuda:0')).eval()
        cfg = model.cfg.decoding
        cfg.strategy = 'greedy_batch'
        model.change_decoding_strategy(cfg)
        assert next(model.parameters()).dtype == torch.float32
    computed, reused = 0, 0
    for index, item in enumerate(inputs):
        path = OUT/'predictions'/(item['id']+'.json')
        if path.exists():
            old = read(path)
            assert old['plan_sha256'] == file_hash(ROOT/'plan.json') and old['item'] == item
            reused += 1
            continue
        x = waveform(item)
        started = time.perf_counter()
        row = {'item': item, 'plan_sha256': file_hash(ROOT/'plan.json'), 'system': system,
            'runtime_failure': None}
        if system == 'canary':
            row.update(transcribe_canary(model, x))
            row['vad_keep'] = speech_present(x)
        else:
            y, info = deep_filter(x, Path('/models/deep-filter'))
            target = OUT/'audio'/(item['id']+'.wav')
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists()
            sf.write(target, y, 16000, subtype='FLOAT')
            with torch.inference_mode():
                response = model.transcribe([str(target)], batch_size=1,
                    return_hypotheses=True, timestamps=True, verbose=False)
            if isinstance(response, tuple):
                response = response[0]
            assert len(response) == 1
            row.update({'hypothesis': response[0].text, 'denoising': info,
                'output_pcm_sha256': pcm(y), 'output_audio_sha256': file_hash(target)})
        row['seconds'] = time.perf_counter()-started
        save(path, row)
        computed += 1
        if (index+1) % 10 == 0 or index+1 == len(inputs):
            print({'system': system, 'completed': index+1, 'total': len(inputs),
                'elapsed_sec': round(time.perf_counter()-start, 1)}, flush=True)
    save(OUT/'execution.json', {'plan_sha256': file_hash(ROOT/'plan.json'), 'system': system,
        'records': len(inputs), 'actual_new_ASR_calls_this_process': computed,
        'reused_completed_predictions': reused, 'device': torch.cuda.get_device_name(0),
        'peak_GPU_bytes': torch.cuda.max_memory_allocated(), 'seconds': time.perf_counter()-start,
        'prediction_sha256': {p.name: file_hash(p) for p in sorted((OUT/'predictions').glob('*.json'))},
        'packages': {n: importlib.metadata.version(n) for n in ('nemo_toolkit', 'torch',
            'transformers', 'peft', 'faster-whisper')}, 'runtime_failures': []})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'canary', 'dfn_parakeet', 'score', 'verify'])
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare()
    elif args.stage in ('score', 'verify'):
        import report_cockpit_candidates_v10
        getattr(report_cockpit_candidates_v10, args.stage)()
    else:
        run(args.stage)
