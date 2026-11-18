"""Train a noise router using synthetic labels, then freeze before evaluation."""
from __future__ import annotations

import argparse
import importlib.metadata
import os
import shutil
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import soundfile as sf
from sklearn.ensemble import ExtraTreesClassifier

from north55_speech.acoustic_noise_router import RECIPE, audio_features, choose_by_noise
from north55_speech.core import file_hash
from north55_speech.robust_adaptation import augment_waveform
from scripts.cockpit_cross_asr_v6 import pcm, read, save

ROOT, OUT = Path('/study'), Path('/output')


def prepare():
    work, prior = Path('/app'), Path('/app/reports/cockpit-selector-v8')
    assert not (ROOT/'plan.json').exists()
    p8 = read(prior/'plan.json')
    assert read(prior/'verification.json')['status'] == 'PASS'
    for name, key in [('inputs.json', 'inputs_sha256'), ('scoring/references.json', 'references_sha256')]:
        assert file_hash(prior/name) == p8[key]
        save(ROOT/name, read(prior/name))
    source = work/'data/curated/cockpit-hard-v4/train.jsonl'
    assert file_hash(source) == read(work/'reports/cockpit-robust-v5/plan.json')['train_sha256']
    import json
    train = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines() if line]
    clean = [s for s in train if not s['variant_of']]
    assert len(train) == 247 and len(clean) == 231
    assert all(s['split'] == 'train' and len(s['speaker_ids']) == 1 for s in clean)
    entries = [{'id': s['sample_id'], 'audio_path': s['audio_path'], 'audio_sha256': s['audio_sha256'],
        'reader': s['speaker_ids'][0]} for s in sorted(clean, key=lambda x: x['sample_id'])]
    assert len({e['reader'] for e in entries}) == 9
    save(ROOT/'train-inputs.json', entries)
    frozen = ROOT/'frozen'
    for directory in ('src', 'scripts'):
        shutil.copytree(work/directory, frozen/directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    code = {p.relative_to(frozen).as_posix(): file_hash(p) for p in sorted(frozen.rglob('*.py'))}
    plan = {'recipe': RECIPE, 'implementation_sha256': code, 'prior_plan_sha256': file_hash(prior/'plan.json'),
        'protocol_sha256': file_hash(ROOT/'protocol.md'), 'train_inputs_sha256': file_hash(ROOT/'train-inputs.json'),
        'source_train_sha256': file_hash(source), 'inputs_sha256': file_hash(ROOT/'inputs.json'),
        'references_sha256': file_hash(ROOT/'scoring/references.json'), 'train_parents': 231,
        'training_observations': 3927, 'training_readers': 9, 'new_ASR_calls': 0,
        'blind_dev_accessed': False, 'test_accessed': False, 'release_promoted': False}
    save(ROOT/'plan.json', plan)
    for name in ('io-train', 'io-infer'):
        (ROOT/name).mkdir(exist_ok=True)
    for path in [ROOT, *ROOT.rglob('*')]:
        os.chown(path, 10001, 10001)
    print({'plan_sha256': file_hash(ROOT/'plan.json'), 'train_parents': 231}, flush=True)


def validate():
    plan = read(ROOT/'plan.json')
    assert plan['recipe'] == RECIPE
    for name, digest in plan['implementation_sha256'].items():
        assert file_hash(Path('/app')/name) == digest
    return plan


def training_rows(entries):
    for index, entry in enumerate(entries):
        path = Path('/audio')/entry['audio_path']
        assert file_hash(path) == entry['audio_sha256']
        x, rate = sf.read(path, dtype='float32')
        assert rate == 16000
        yield {**entry, 'seed': None, 'snr_db': None, 'label': 0, 'pcm_sha256': pcm(x)}, audio_features(x)
        for variant in range(RECIPE['variants_per_level']):
            seed = RECIPE['augmentation_seed_start'] + 4*index + variant
            for snr in RECIPE['snr_db']:
                wave, details = augment_waveform(x, seed, snr)
                yield {**entry, 'seed': seed, 'snr_db': snr,
                    'label': int(snr in RECIPE['positive_snr_db']), 'pcm_sha256': pcm(wave),
                    'augmentation': details}, audio_features(wave)
        if (index+1) % 30 == 0 or index+1 == len(entries):
            print({'feature_parents': index+1, 'total': len(entries)}, flush=True)


def estimator():
    return ExtraTreesClassifier(n_estimators=RECIPE['trees'], max_depth=RECIPE['max_depth'],
        min_samples_leaf=RECIPE['min_samples_leaf'], class_weight='balanced',
        random_state=RECIPE['seed'], n_jobs=4)


def train():
    plan = validate()
    assert not (OUT/'training.json').exists() and not (OUT/'router.joblib').exists()
    assert file_hash(ROOT/'train-inputs.json') == plan['train_inputs_sha256']
    rows, matrix = [], []
    for row, f in training_rows(read(ROOT/'train-inputs.json')):
        rows.append(row)
        matrix.append(f)
    X = np.vstack(matrix)
    y = np.asarray([r['label'] for r in rows])
    groups = np.asarray([r['reader'] for r in rows])
    assert X.shape == (3927, 62)
    oof = np.full(len(y), np.nan)
    folds = []
    for group in sorted(set(groups)):
        held = groups == group
        model = estimator().fit(X[~held], y[~held])
        oof[held] = model.predict_proba(X[held])[:, 1]
        folds.append({'held_reader': group, 'train_readers': sorted(set(groups[~held])),
            'train_rows': int((~held).sum()), 'held_rows': int(held.sum())})
        print({'held_reader_completed': group}, flush=True)
    assert np.isfinite(oof).all()
    threshold = max(RECIPE['threshold_floor'], float(np.quantile(oof[y == 0], RECIPE['negative_oof_quantile'], method='higher')))
    final = estimator().fit(X, y)
    joblib.dump(final, OUT/'router.joblib')
    np.savez_compressed(OUT/'features.npz', X=X, y=y, groups=groups, oof=oof)
    save(OUT/'feature-rows.json', rows)
    groups_result = {}
    for name, mask in [('clean', np.asarray([r['seed'] is None for r in rows])),
        ('severe', y == 1), ('mild', np.asarray([r['snr_db'] in (15, 25) for r in rows]))]:
        groups_result[name] = {'rows': int(mask.sum()), 'selected_severe': int((oof[mask] >= threshold).sum())}
    result = {'plan_sha256': file_hash(ROOT/'plan.json'), 'train_parents': 231, 'observations': len(rows),
        'threshold': threshold, 'folds': folds, 'OOF': groups_result, 'trees': len(final.estimators_),
        'features': final.n_features_in_, 'files': {name: file_hash(OUT/name)
            for name in ('router.joblib', 'features.npz', 'feature-rows.json')},
        'labels_are_synthetic_severity': True, 'ASR_texts_used_for_training': False,
        'dev_used_for_training_or_threshold': False, 'sklearn': importlib.metadata.version('scikit-learn')}
    save(OUT/'training.json', result)
    print({'training': groups_result, 'threshold': threshold}, flush=True)


def waveform(item):
    path = (Path('/cross')/item['audio_path']).resolve()
    assert path.is_relative_to(Path('/cross/input-audio')) and file_hash(path) == item['audio_sha256']
    x, rate = sf.read(path, dtype='float32')
    assert rate == 16000 and pcm(x) == item['pcm_sha256']
    return x


def infer():
    plan = validate()
    assert file_hash(ROOT/'inputs.json') == plan['inputs_sha256']
    training = read(Path('/trained/training.json'))
    assert training['plan_sha256'] == file_hash(ROOT/'plan.json')
    for name, digest in training['files'].items():
        assert file_hash(Path('/trained')/name) == digest
    model = joblib.load('/trained/router.joblib')
    items = read(ROOT/'inputs.json')
    results = []
    for item in items:
        f = probability = None
        if item['language'] == 'en' and item['parakeet'].strip():
            f = audio_features(waveform(item))
            probability = float(model.predict_proba(f[None])[0, 1])
        route = choose_by_noise(item['whisper'], item['parakeet'], item['language'], probability, training['threshold'])
        results.append({'id': item['id'], **route, 'severe_probability': probability,
            'features': f.tolist() if f is not None else None, 'pcm_sha256': item['pcm_sha256']})
    save(OUT/'decisions.json', results)
    save(OUT/'execution.json', {'plan_sha256': file_hash(ROOT/'plan.json'),
        'training_sha256': file_hash(Path('/trained/training.json')), 'records': len(results),
        'decisions_sha256': file_hash(OUT/'decisions.json'), 'threshold': training['threshold'],
        'reasons': dict(Counter(r['reason'] for r in results)), 'new_ASR_calls': 0,
        'device': 'cpu', 'runtime_failures': []})
    print({'decisions': len(results), 'reasons': dict(Counter(r['reason'] for r in results))}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'train', 'infer', 'score', 'verify'])
    stage = parser.parse_args().stage
    if stage in ('score', 'verify'):
        from scripts import report_cockpit_noise_router_v9
        getattr(report_cockpit_noise_router_v9, stage)()
    else:
        globals()[stage]()
