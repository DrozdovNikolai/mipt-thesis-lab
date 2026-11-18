"""Independent ASR diagnostic. Inference receives audio and metadata only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import time
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.core import file_hash

STUDY, EXP, WORK = Path('/study'), Path('/experiment'), Path('/workspace')
SYSTEMS = ('baseline', 'uniform', 'balanced', 'balanced-silence')


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError('Preserve existing artifact: '+str(path))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def pcm(x):
    return hashlib.sha256(x.astype('<f4').tobytes()).hexdigest()


def prepare():
    from scripts.decoding_diagnostics import load_audio

    if (STUDY/'inference/plan.json').exists():
        raise ValueError('Preserve frozen experiment')
    prior, hard = WORK/'reports/cockpit-robust-v5', WORK/'reports/cockpit-hard-v4'
    old = read(prior/'plan.json')
    for name, field in [('inputs.json', 'inputs_sha256'), ('scoring/references.json', 'references_sha256')]:
        assert file_hash(prior/name) == old[field]
    assert file_hash(WORK/'data/curated/cockpit-hard-v4/train.jsonl') == old['train_sha256']
    all_items = read(prior/'inputs.json')
    selected = [i for i in all_items if i['cohort'] != 'general_ru']
    assert len(selected) == 491
    refs = read(prior/'scoring/references.json')
    gate = read(prior/'io-vad/vad.json')
    assert gate['plan_sha256'] == file_hash(prior/'plan.json')
    gates = {g['id']: g for g in gate['rows']}
    historical = {i['id']: {} for i in selected}
    history_hashes = {}
    for system in SYSTEMS:
        execution = read(prior/('io-'+system)/'execution.json')
        assert execution['plan_sha256'] == file_hash(prior/'plan.json') and not execution['runtime_failures']
        history_hashes[system] = file_hash(prior/('io-'+system)/'execution.json')
        for item in selected:
            path = prior/('io-'+system)/'predictions'/(item['id']+'.json')
            assert file_hash(path) == execution['prediction_sha256'][path.name]
            row = read(path)
            assert not row['runtime_failure']
            assert all(row.get(k) == v for k, v in item.items())
            historical[item['id']][system] = row
    hard_plan = read(hard/'inference/plan.json')
    assert file_hash(hard/'inference/inputs.json') == hard_plan['inputs_sha256']
    for name, digest in hard_plan['scoring_sha256'].items():
        assert file_hash(hard/'scoring'/name) == digest
    decisions = read(hard/'decisions.json')
    rejected = {d['id']: d for d in decisions if not d['accepted']}
    assert len(rejected) == 352
    cached, sources = read(hard/'scoring/cached.json'), read(hard/'scoring/sources.json')
    assert all(s['split'] == 'train' for s in sources.values())
    execution = read(hard/'predictions/execution.json')
    assert execution['plan_sha256'] == file_hash(hard/'inference/plan.json') and not execution['failures']
    disputed = {}
    for item in read(hard/'inference/inputs.json'):
        if item['id'] not in rejected:
            continue
        path = hard/'predictions'/(item['id']+'.json')
        assert file_hash(path) == execution['prediction_sha256'][path.name]
        identity = 'disputed-'+item['id']
        disputed[identity] = {'item': item, 'old_decision': rejected[item['id']],
            'medium': cached[item['id']]['medium'], 'large': read(path), 'small': cached[item['id']]['small']}
        selected.append({**item, 'id': identity, 'reference_id': None, 'gain_db': 0.,
            'cohort': 'disputed_train', 'group_id': sources[item['source']]['session_id'], 'input_language': 'en'})
    assert len(selected) == len({i['id'] for i in selected}) == 843
    directory = EXP/'input-audio'
    directory.mkdir(exist_ok=True)
    inputs = []
    for item in selected:
        if item.get('synthetic_v5'):
            path = Path('/robust/eval-audio')/(item['id']+'.wav')
            assert file_hash(path) == item['audio_sha256']
            x, rate = sf.read(path, dtype='float32')
            assert rate == 16000 and pcm(x) == item['effective_waveform_sha256']
        else:
            x = load_audio(item)
        assert x.ndim == 1 and np.isfinite(x).all()
        if item['id'] in historical:
            assert all(p['effective_waveform_sha256'] == pcm(x) for p in historical[item['id']].values())
            assert gates[item['id']]['pcm_sha256'] == pcm(x)
        path = directory/(item['id']+'.wav')
        if path.exists():
            existing, rate = sf.read(path, dtype='float32')
            assert rate == 16000 and pcm(existing) == pcm(x)
        else:
            sf.write(path, x, 16000, subtype='FLOAT')
        inputs.append({'id': item['id'], 'cohort': item['cohort'], 'group_id': item['group_id'],
            'audio_path': str(path.relative_to(EXP)), 'audio_sha256': file_hash(path),
            'pcm_sha256': pcm(x), 'duration_sec': len(x)/16000})
    save(STUDY/'scoring/original-inputs.json', selected)
    save(STUDY/'scoring/references.json', {i['id']: refs[i['reference_id']] for i in selected if i['id'] not in disputed})
    save(STUDY/'scoring/historical.json', historical)
    save(STUDY/'scoring/gates.json', {i['id']: gates[i['id']] for i in selected if i['id'] not in disputed})
    save(STUDY/'scoring/disputed.json', disputed)
    save(STUDY/'scoring/documents.json', read(hard/'scoring/documents.json'))
    save(STUDY/'scoring/sources.json', sources)
    train = [json.loads(line) for line in (WORK/'data/curated/cockpit-hard-v4/train.jsonl').read_text(encoding='utf-8').splitlines() if line]
    save(STUDY/'scoring/train.json', train)
    save(STUDY/'inference/inputs.json', inputs)
    frozen = STUDY/'frozen'
    for folder in ('src', 'scripts'):
        shutil.copytree(WORK/folder, frozen/folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    code = {p.relative_to(frozen).as_posix(): file_hash(p) for p in sorted(frozen.rglob('*.py'))}
    plan = {'model': read(STUDY/'model-manifest.json'), 'protocol_sha256': file_hash(STUDY/'protocol.md'),
        'prior_plan_sha256': file_hash(prior/'plan.json'),
        'hard_plan_sha256': file_hash(hard/'inference/plan.json'), 'historical_execution_sha256': history_hashes,
        'implementation_sha256': code, 'inputs_sha256': file_hash(STUDY/'inference/inputs.json'),
        'scoring_sha256': {p.name: file_hash(p) for p in (STUDY/'scoring').iterdir()},
        'cohorts': dict(Counter(i['cohort'] for i in inputs)), 'decoding': {'batch_size': 4,
        'strategy': 'greedy_batch', 'timestamps': True, 'precision': 'float32', 'vad': False},
        'new_ASR_calls': len(inputs), 'quality_evidence': False, 'release_promoted': False,
        'blind_dev_accessed': False, 'test_accessed': False,
        'recovery_policy': {'teacher_disagreement': .08, 'exact_below_words': 8,
            'minimum_words': 4, 'publisher_coverage': .9, 'critical_and_numeric_agreement': True,
            'whisper_median_probability': .65, 'maximum_collapsed_timestamps': .25,
            'target': 'unprompted_parakeet', 'human_verified': False, 'maximum_speech_words_per_second': 5.}}
    save(STUDY/'inference/plan.json', plan)
    print(json.dumps({'inputs': len(inputs), 'cohorts': plan['cohorts']}), flush=True)


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, 'detach'):
        return value.detach().cpu().tolist()
    return value


def infer():
    import torch
    from nemo.collections.asr.models import ASRModel
    from omegaconf import OmegaConf

    torch.set_num_threads(4)
    plan = read(STUDY/'plan.json')
    assert file_hash(STUDY/'inputs.json') == plan['inputs_sha256']
    for name, digest in plan['implementation_sha256'].items():
        assert file_hash(Path('/code')/name) == digest
    model_path = EXP/'parakeet/parakeet-tdt-0.6b-v2.nemo'
    assert file_hash(model_path) == plan['model']['files'][model_path.name]['sha256']
    assert torch.cuda.is_available()
    model = ASRModel.restore_from(str(model_path), map_location=torch.device('cuda:0'))
    model.eval()
    cfg = model.cfg.decoding
    cfg.strategy = plan['decoding']['strategy']
    model.change_decoding_strategy(cfg)
    output = Path('/output')
    if not (output/'resolved-model-config.json').exists():
        save(output/'resolved-model-config.json', OmegaConf.to_container(model.cfg, resolve=True))
    items = read(STUDY/'inputs.json')
    pending, hashes = [], {}
    plan_hash = file_hash(STUDY/'plan.json')
    for item in items:
        path = output/(item['id']+'.json')
        if path.exists():
            existing = read(path)
            assert existing['plan_sha256'] == plan_hash and existing['pcm_sha256'] == item['pcm_sha256'] and not existing['error']
            hashes[path.name] = file_hash(path)
        else:
            pending.append(item)
    started = time.perf_counter()
    count = 0
    for offset in range(0, len(pending), 4):
        batch = pending[offset:offset+4]
        paths = []
        for item in batch:
            path = (EXP/item['audio_path']).resolve()
            assert path.is_relative_to(EXP/'input-audio') and file_hash(path) == item['audio_sha256']
            x, rate = sf.read(path, dtype='float32')
            assert rate == 16000 and pcm(x) == item['pcm_sha256']
            paths.append(str(path))
        with torch.inference_mode():
            predictions = model.transcribe(paths, batch_size=4, return_hypotheses=True, timestamps=True, verbose=False)
        if isinstance(predictions, tuple):
            predictions = predictions[0]
        assert len(predictions) == len(batch)
        for item, prediction in zip(batch, predictions, strict=True):
            row = {**item, 'plan_sha256': plan_hash, 'hypothesis': prediction.text,
                'timestamp': plain(prediction.timestamp), 'error': None, 'device': str(model.device),
                'precision': str(next(model.parameters()).dtype)}
            path = output/(item['id']+'.json')
            save(path, row)
            hashes[path.name] = file_hash(path)
        count += len(batch)
        if count % 40 == 0 or count == len(pending):
            print(json.dumps({'completed': count, 'pending_total': len(pending), 'seconds': round(time.perf_counter()-started, 2)}), flush=True)
    save(output/('execution.json' if not (output/'execution.json').exists() else f'replay-{time.time_ns()}.json'),
        {'plan_sha256': plan_hash, 'prediction_sha256': hashes, 'records': len(hashes), 'new_ASR_calls': len(pending),
         'failures': [], 'seconds': time.perf_counter()-started, 'device': str(model.device),
         'GPU': torch.cuda.get_device_name(0), 'precision': str(next(model.parameters()).dtype),
         'packages': {p: importlib.metadata.version(p) for p in ('nemo_toolkit', 'torch', 'torchaudio', 'transformers', 'numpy')}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'infer', 'score'])
    stage = parser.parse_args().stage
    if stage == 'score':
        from scripts.report_cockpit_cross_asr_v6 import score
        score()
    else:
        globals()[stage]()
