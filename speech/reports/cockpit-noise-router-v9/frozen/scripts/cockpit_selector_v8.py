"""Frozen acoustic selection between existing Whisper and Parakeet responses."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

import soundfile as sf

from north55_speech.core import file_hash
from north55_speech.cross_asr_selection import POLICY, AcousticSelector, shortcut
from scripts.cockpit_cross_asr_v6 import pcm, read, save

ROOT, OUT, AUDIO = Path('/study'), Path('/output'), Path('/cross')
MODEL = Path('/models/whisper-medium-en-ct2')


def prepare():
    work = Path('/app')
    prior, cross = (work/'reports'/s for s in ('cockpit-robust-v5', 'cockpit-cross-asr-v6'))
    if (ROOT/'plan.json').exists():
        raise ValueError('Preserve frozen plan')
    p5, p6 = read(prior/'plan.json'), read(cross/'inference/plan.json')
    assert file_hash(prior/'inputs.json') == p5['inputs_sha256']
    assert file_hash(prior/'scoring/references.json') == p5['references_sha256']
    assert file_hash(cross/'inference/inputs.json') == p6['inputs_sha256']
    gates = read(prior/'io-vad/vad.json')
    assert gates['plan_sha256'] == file_hash(prior/'plan.json')
    gate_by_id = {r['id']: r for r in gates['rows']}
    originals = read(prior/'inputs.json')
    refs = read(prior/'scoring/references.json')
    english = {i['id']: i for i in read(cross/'inference/inputs.json') if i['cohort'] != 'disputed_train'}
    assert len(originals) == 541 and len(english) == 491
    assert read(cross/'verification.json')['status'] == 'PASS'
    ex6 = read(cross/'predictions/execution.json')
    assert not ex6['failures'] and ex6['plan_sha256'] == file_hash(cross/'inference/plan.json')
    ex5 = {s: read(prior/('io-'+s)/'execution.json') for s in ('baseline', 'balanced')}
    assert all(not e['runtime_failures'] and e['plan_sha256'] == file_hash(prior/'plan.json') for e in ex5.values())
    inputs, scoring, provenance = [], {}, {}
    for item in originals:
        identity = item['id']
        old = {}
        for system in ex5:
            path = prior/('io-'+system)/'predictions'/(identity+'.json')
            assert file_hash(path) == ex5[system]['prediction_sha256'][path.name]
            old[system] = read(path)
            assert not old[system]['runtime_failure']
            provenance[path.relative_to(work).as_posix()] = file_hash(path)
        waveform_hash = old['balanced']['effective_waveform_sha256']
        assert old['baseline']['effective_waveform_sha256'] == waveform_hash == gate_by_id[identity]['pcm_sha256']
        # Match the existing English Parakeet study population. "auto" was a
        # Whisper decoding option, not an independently known source language.
        profile_language = 'ru' if item['input_language'] == 'ru' else 'en'
        row = {'id': identity, 'language': profile_language, 'original_input_language': item['input_language'],
            'whisper': old['balanced']['hypothesis'],
            'parakeet': None, 'pcm_sha256': waveform_hash, 'duration_sec': item['duration_sec']}
        if row['language'] == 'en':
            source = english[identity]
            path = cross/'predictions'/(identity+'.json')
            assert file_hash(path) == ex6['prediction_sha256'][path.name]
            prediction = read(path)
            assert not prediction['error'] and prediction['pcm_sha256'] == waveform_hash
            audio_path = AUDIO/source['audio_path']
            assert file_hash(audio_path) == source['audio_sha256']
            x, rate = sf.read(audio_path, dtype='float32')
            assert rate == 16000 and pcm(x) == waveform_hash and 0 < len(x) <= 480000
            row.update(parakeet=prediction['hypothesis'], audio_path=source['audio_path'],
                audio_sha256=source['audio_sha256'])
            provenance[path.relative_to(work).as_posix()] = file_hash(path)
        else:
            assert row['language'] == 'ru'
        inputs.append(row)
        scoring[identity] = {'cohort': item['cohort'], 'group_id': item['group_id'],
            'reference': refs[item['reference_id']], 'baseline': old['baseline']['hypothesis'],
            'vad_keep': gate_by_id[identity]['keep']}
    save(ROOT/'inputs.json', inputs)
    save(ROOT/'scoring/references.json', scoring)
    save(ROOT/'provenance.json', provenance)
    frozen = ROOT/'frozen'
    for directory in ('src', 'scripts'):
        shutil.copytree(work/directory, frozen/directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    code = {p.relative_to(frozen).as_posix(): file_hash(p) for p in sorted(frozen.rglob('*.py'))}
    train_ids = sorted(i['id'] for i in inputs if scoring[i['id']]['cohort'] == 'train_retained_fit'
        and shortcut(i['whisper'], i['parakeet'], i['language']) is None)
    plan = {'policy': POLICY, 'inputs_sha256': file_hash(ROOT/'inputs.json'),
        'references_sha256': file_hash(ROOT/'scoring/references.json'),
        'provenance_sha256': file_hash(ROOT/'provenance.json'), 'protocol_sha256': file_hash(ROOT/'protocol.md'),
        'implementation_sha256': code,
        'judge_files': {p.name: file_hash(p) for p in sorted(MODEL.iterdir()) if p.is_file()},
        'prior_plan_sha256': file_hash(prior/'plan.json'), 'cross_plan_sha256': file_hash(cross/'inference/plan.json'),
        'cpu_smoke_ids': train_ids[:2], 'gpu_replay_ids': train_ids[:2], 'compute_type': 'float32',
        'records': len(inputs), 'cohorts': dict(Counter(r['cohort'] for r in scoring.values())),
        'quality_evidence': False, 'blind_dev_accessed': False, 'test_accessed': False,
        'reused_ASR': {'baseline': 541, 'balanced': 541, 'parakeet': 491}, 'new_ASR': 0,
        'new_training_updates': 0, 'release_promoted': False}
    save(ROOT/'plan.json', plan)
    for path in [ROOT, *ROOT.rglob('*')]:
        os.chown(path, 10001, 10001)
    print(json.dumps({'prepared': len(inputs), 'plan_sha256': file_hash(ROOT/'plan.json'),
        'needs_acoustic_rescoring': sum(shortcut(i['whisper'], i['parakeet'], i['language']) is None for i in inputs)}), flush=True)


def validate():
    plan = read(ROOT/'plan.json')
    assert plan['policy'] == POLICY
    assert file_hash(ROOT/'inputs.json') == plan['inputs_sha256']
    for name, digest in plan['implementation_sha256'].items():
        assert file_hash(Path('/app')/name) == digest
    for name, digest in plan['judge_files'].items():
        assert file_hash(MODEL/name) == digest
    return plan


def audio(item):
    path = (AUDIO/item['audio_path']).resolve()
    assert path.is_relative_to(AUDIO/'input-audio') and file_hash(path) == item['audio_sha256']
    x, rate = sf.read(path, dtype='float32')
    assert rate == 16000 and x.ndim == 1 and pcm(x) == item['pcm_sha256']
    return x


def infer(device='cuda', replay=False):
    plan = validate()
    if (OUT/'execution.json').exists():
        raise ValueError('Preserve completed inference')
    inputs = read(ROOT/'inputs.json')
    if device == 'cpu' or replay:
        ids = plan['cpu_smoke_ids' if device == 'cpu' else 'gpu_replay_ids']
        inputs = [i for i in inputs if i['id'] in ids]
        assert len(inputs) == 2
    started = time.perf_counter()
    selector = AcousticSelector(MODEL, device, plan['compute_type'])
    hashes, totals = {}, Counter()
    for index, item in enumerate(inputs):
        path = OUT/'predictions'/(item['id']+'.json')
        if path.exists():
            row = read(path)
            assert row['plan_sha256'] == file_hash(ROOT/'plan.json') and row['input'] == item
            assert row['device'] == device and row['compute_type'] == plan['compute_type']
        else:
            before = time.perf_counter()
            x = audio(item) if item['language'] == 'en' else None
            result = selector.choose(x, item['whisper'], item['parakeet'], item['language'])
            row = {'plan_sha256': file_hash(ROOT/'plan.json'), 'input': item, **result,
                'device': device, 'compute_type': selector.model.model.compute_type,
                'seconds': time.perf_counter()-before, 'runtime_failure': None}
            save(path, row)
        hashes[path.name] = file_hash(path)
        totals['encoder_calls'] += row['encoder_calls']
        totals['alignment_calls'] += row['alignment_calls']
        totals[row['reason']] += 1
        if (index+1) % 40 == 0 or index+1 == len(inputs):
            print(json.dumps({'completed': index+1, 'total': len(inputs), 'seconds': time.perf_counter()-started}), flush=True)
    save(OUT/'execution.json', {'records': len(inputs), 'plan_sha256': file_hash(ROOT/'plan.json'),
        'device': selector.model.model.device, 'compute_type': selector.model.model.compute_type,
        'prediction_sha256': hashes, 'totals': dict(totals), 'seconds': time.perf_counter()-started,
        'runtime_failures': [], 'new_ASR_calls': 0, 'replay': replay,
        'packages': {p: importlib.metadata.version(p) for p in ('faster-whisper', 'ctranslate2', 'numpy')}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'infer', 'score', 'verify'])
    parser.add_argument('--cpu', action='store_true')
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    if args.stage in ('score', 'verify'):
        from scripts import report_cockpit_selector_v8
        getattr(report_cockpit_selector_v8, args.stage)()
    elif args.stage == 'infer':
        infer('cpu' if args.cpu else 'cuda', args.replay)
    else:
        prepare()
