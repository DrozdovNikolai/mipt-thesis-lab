"""Check the unchanged consensus rule using fresh batch-one Parakeet on every English input."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import joblib
import soundfile as sf

from north55_speech.acoustic_noise_router import audio_features
from north55_speech.cockpit_candidates_v10 import speech_present
from north55_speech.cockpit_consensus_v11 import select_consensus
from north55_speech.core import file_hash

OUT = Path('/output')


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def infer():
    import torch
    from nemo.collections.asr.models import ASRModel
    start = time.perf_counter()
    assert not (OUT/'plan.json').exists()
    training = read('/trained/training.json')
    assert file_hash(Path('/trained/router.joblib')) == training['files']['router.joblib']
    config = {'purpose': 'Validate the already fixed v11 edit-consensus rule in local batch-one Parakeet mode',
        'inputs_sha256': file_hash(Path('/inputs.json')), 'canary_execution_sha256': file_hash(Path('/canary-execution.json')),
        'script_sha256': file_hash(Path(__file__)),
        'implementation_sha256': {n: file_hash(Path('/app/src/north55_speech')/n) for n in
            ('cockpit_consensus_v11.py', 'cockpit_candidates_v10.py', 'acoustic_noise_router.py', 'metrics.py')},
        'training_sha256': file_hash(Path('/trained/training.json')), 'threshold': training['threshold'],
        'batch_size': 1, 'parakeet_dtype': 'float32', 'strategy': 'greedy_batch',
        'timestamps': True, 'seed': 55, 'planned_new_ASR_calls': 491,
        'reference_access_for_inference': False, 'blind_dev_accessed': False, 'test_accessed': False,
        'selection_policy_changed': False}
    save(OUT/'plan.json', config)
    print({'frozen_plan_sha256': file_hash(OUT/'plan.json')}, flush=True)
    torch.set_num_threads(4)
    torch.manual_seed(55)
    path = Path('/cross/parakeet/parakeet-tdt-0.6b-v2.nemo')
    assert file_hash(path) == 'd99e39955c9d3d0350d8fb7c75e40c64a2b2eaeb003883d7c941fd2e8747b28c'
    model = ASRModel.restore_from(str(path), map_location=torch.device('cuda:0')).eval()
    cfg = model.cfg.decoding
    cfg.strategy = 'greedy_batch'
    model.change_decoding_strategy(cfg)
    assert next(model.parameters()).dtype == torch.float32
    router = joblib.load('/trained/router.joblib')
    canary_execution = read('/canary-execution.json')
    rows, calls = [], 0
    for item in read('/inputs.json'):
        identity = item['id']
        if item['language'] == 'ru':
            rows.append({'id': identity, 'base': item['whisper'], 'hypothesis': item['whisper'],
                'parakeet': None, 'accepted_edits': [], 'reason': 'russian_passthrough'})
            continue
        path = Path('/cross')/item['audio_path']
        assert file_hash(path) == item['audio_sha256']
        x, rate = sf.read(path, dtype='float32')
        assert rate == 16000 and hashlib.sha256(x.astype('<f4').tobytes()).hexdigest() == item['pcm_sha256']
        with torch.inference_mode():
            answer = model.transcribe([str(path)], batch_size=1, return_hypotheses=True,
                timestamps=True, verbose=False)
        if isinstance(answer, tuple):
            answer = answer[0]
        para = answer[0].text
        probability = float(router.predict_proba(audio_features(x)[None])[0, 1]) if para.strip() else None
        vad = speech_present(x) if not para.strip() else None
        severe = probability is not None and probability >= training['threshold']
        if severe:
            base, reason = para, 'severe_noise'
        elif para.strip() or vad:
            base, reason = item['whisper'], 'whisper'
        else:
            base, reason = '', 'empty_decoder_and_no_speech'
        cpath = Path('/canary-predictions')/(identity+'.json')
        assert file_hash(cpath) == canary_execution['prediction_sha256'][cpath.name]
        canary = read(cpath)['hypothesis']
        decision = select_consensus(base, para, canary, 'en', severe)
        row = {'id': identity, 'base': base, 'hypothesis': decision['edits'], 'parakeet': para,
            'accepted_edits': decision['accepted_edits'], 'probability': probability,
            'vad_on_empty': vad, 'reason': reason, 'pcm_sha256': item['pcm_sha256'],
            'parakeet_matches_batch_four': para == item['parakeet']}
        save(OUT/'predictions'/(identity+'.json'), row)
        rows.append(row)
        calls += 1
        if calls % 25 == 0 or calls == 491:
            print({'completed': calls, 'total': 491, 'elapsed_sec': round(time.perf_counter()-start, 1)}, flush=True)
    save(OUT/'decisions.json', rows)
    save(OUT/'execution.json', {'status': 'COMPLETE', 'plan_sha256': file_hash(OUT/'plan.json'),
        'new_GPU_ASR_calls': calls, 'decisions_sha256': file_hash(OUT/'decisions.json'),
        'parakeet_differences': sum(not r.get('parakeet_matches_batch_four', True) for r in rows),
        'seconds': time.perf_counter()-start, 'peak_GPU_bytes': torch.cuda.max_memory_allocated()})


def score():
    from rapidfuzz.distance import Levenshtein

    from north55_speech.metrics import (
        corpus_counts,
        edit_counts,
        lexical_normalizer_v1,
        paired_cluster_bootstrap,
    )
    root = Path('/workspace/reports')
    prior, study = root/'cockpit-candidates-v10', root/'cockpit-consensus-v11'
    execution = read(OUT/'execution.json')
    assert execution['decisions_sha256'] == file_hash(OUT/'decisions.json')
    assert execution['plan_sha256'] == file_hash(OUT/'plan.json')
    refs, items = read(prior/'scoring/references.json'), read(prior/'inputs.json')
    assert file_hash(prior/'inputs.json') == read(OUT/'plan.json')['inputs_sha256']
    previous = {r['id']: r for r in read(study/'io-infer/decisions.json')}
    original = read(prior/'composed-predictions.json')
    rows = {r['id']: r for r in read(OUT/'decisions.json')}
    assert len(rows) == len(items) == 541
    systems = ('v9', 'guarded_v9', 'v11_cached', 'fresh_base', 'v11_fresh')
    counts, distances, changes = {}, 0, []
    for item in items:
        identity = item['id']
        row = rows[identity]
        texts = {'v9': original[identity]['v9'], 'guarded_v9': original[identity]['guarded_v9'],
            'v11_cached': previous[identity]['edits'], 'fresh_base': row['base'], 'v11_fresh': row['hypothesis']}
        counts[identity] = {}
        for system, text in texts.items():
            for mode in ('raw', 'gate'):
                emitted = text if mode == 'raw' or refs[identity]['vad_keep'] else ''
                c = edit_counts(refs[identity]['reference'], emitted)
                a, b = [lexical_normalizer_v1(t).split() for t in (refs[identity]['reference'], emitted)]
                assert c['S']+c['D']+c['I'] == Levenshtein.distance(a, b)
                counts[identity][system+'-'+mode] = c
                distances += 1
        if texts['v11_cached'] != texts['v11_fresh']:
            changes.append({'id': identity, 'cohort': refs[identity]['cohort'], 'cached': texts['v11_cached'],
                'fresh': texts['v11_fresh'], 'reference': refs[identity]['reference']})
    cohorts = {}
    for cohort in sorted({r['cohort'] for r in refs.values()}):
        chosen = [i for i in items if refs[i['id']]['cohort'] == cohort]
        aggregate = {s+'-'+m: corpus_counts([counts[i['id']][s+'-'+m] for i in chosen])
            for s in systems for m in ('raw', 'gate')}
        ci = paired_cluster_bootstrap([{'group_id': refs[i['id']]['group_id'],
            'baseline': counts[i['id']]['v9-raw'], 'candidate': counts[i['id']]['v11_fresh-raw']}
            for i in chosen], resamples=2000, seed=55) if 'dev' in cohort else None
        cohorts[cohort] = {'samples': len(chosen), 'scores': aggregate, 'vs_v9_CI': ci,
            'nonempty_fresh': sum(bool(rows[i['id']]['hypothesis'].strip()) for i in chosen)}
    target = ['partial_human_dev', 'publisher_weak_dev', 'quiet_partial_human_dev',
        'acoustic_15_partial_human_dev', 'acoustic_15_publisher_weak_dev',
        'acoustic_5_partial_human_dev', 'acoustic_5_publisher_weak_dev']
    def wer(c, s):
        return cohorts[c]['scores'][s+'-raw']['wer_lexical_corpus']
    checks = {'cockpit_preserved_vs_v9': all(wer(c, 'v11_fresh') <= wer(c, 'v9') for c in target),
        'cockpit_improved': any(wer(c, 'v11_fresh') < wer(c, 'v9') for c in target),
        'EN_control': wer('general_clean', 'v11_fresh') <= wer('general_clean', 'v9')+.01,
        'RU_control': wer('general_ru', 'v11_fresh') == wer('general_ru', 'v9'),
        'nonspeech_empty': all(cohorts[c]['nonempty_fresh'] == 0
            for c in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'))}
    save(OUT/'comparison.json', {'cohorts': cohorts, 'checks': checks, 'diagnostic_pass': all(checks.values()),
        'independent_quality_acceptance': False, 'plan_sha256': file_hash(OUT/'plan.json')})
    save(OUT/'scored-counts.json', counts)
    save(OUT/'changed-results.json', changes)
    save(OUT/'verification.json', {'status': 'PASS', 'new_GPU_ASR_calls': 491,
        'parakeet_differences': execution['parakeet_differences'], 'final_text_differences': len(changes),
        'independent_edit_totals': distances, 'records': 541, 'diagnostic_checks': checks})
    print({'diagnostic_pass': all(checks.values()), 'changed_results': len(changes),
        'WER': {c: {s: wer(c,s) for s in systems} for c in target}}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['infer', 'score'])
    globals()[parser.parse_args().stage]()
