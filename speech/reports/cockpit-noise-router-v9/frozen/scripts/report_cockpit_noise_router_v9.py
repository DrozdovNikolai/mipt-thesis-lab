"""Evaluate a frozen noise router without using references in routing."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import joblib
import numpy as np
from rapidfuzz.distance import Levenshtein

from north55_speech.acoustic_noise_router import audio_features
from north55_speech.core import file_hash
from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    lexical_normalizer_v1,
    paired_cluster_bootstrap,
)
from scripts.cockpit_cross_asr_v6 import read, save
from scripts.cockpit_noise_router_v9 import ROOT, training_rows, validate, waveform


def records():
    plan = validate()
    for name, key in [('inputs.json', 'inputs_sha256'), ('scoring/references.json', 'references_sha256'),
        ('protocol.md', 'protocol_sha256'), ('train-inputs.json', 'train_inputs_sha256')]:
        assert file_hash(ROOT/name) == plan[key]
    training = read(ROOT/'io-train/training.json')
    execution = read(ROOT/'io-infer/execution.json')
    assert execution['training_sha256'] == file_hash(ROOT/'io-train/training.json')
    assert execution['decisions_sha256'] == file_hash(ROOT/'io-infer/decisions.json')
    assert execution['plan_sha256'] == training['plan_sha256'] == file_hash(ROOT/'plan.json')
    assert not execution['runtime_failures'] and execution['records'] == 541
    for name, digest in training['files'].items():
        assert file_hash(ROOT/'io-train'/name) == digest
    results = {r['id']: r for r in read(ROOT/'io-infer/decisions.json')}
    items = read(ROOT/'inputs.json')
    assert len(results) == len(items) == 541
    for item in items:
        row = results[item['id']]
        assert row['hypothesis'] == item[row['selected']] and row['pcm_sha256'] == item['pcm_sha256']
    return plan, items, results, training


def hypotheses(item, meta, row):
    result = {'baseline': meta['baseline'], 'whisper': item['whisper'], 'router': row['hypothesis']}
    if item['parakeet'] is not None:
        result['parakeet'] = item['parakeet']
    return result


def score():
    plan, items, results, training = records()
    refs = read(ROOT/'scoring/references.json')
    counts, examples = {}, []
    for item in items:
        identity = item['id']
        meta, row = refs[identity], results[identity]
        counts[identity] = {}
        for name, text in hypotheses(item, meta, row).items():
            counts[identity][name+'-raw'] = edit_counts(meta['reference'], text)
            counts[identity][name+'-gate'] = edit_counts(meta['reference'], text if meta['vad_keep'] else '')
        if meta['cohort'] in ('partial_human_dev', 'acoustic_5_partial_human_dev'):
            examples.append({'id': identity, 'reference': meta['reference'], 'cohort': meta['cohort'],
                'hypotheses': hypotheses(item, meta, row), 'route': row, 'counts': counts[identity]})
    cohorts = {}
    for cohort in sorted({m['cohort'] for m in refs.values()}):
        selected = [i for i in items if refs[i['id']]['cohort'] == cohort]
        minutes = sum(i['duration_sec'] for i in selected)/60
        aggregate = {}
        for key in counts[selected[0]['id']]:
            aggregate[key] = corpus_counts([counts[i['id']][key] for i in selected])
            aggregate[key]['inserted_words_per_minute'] = aggregate[key]['I']/minutes
        comparisons = {}
        if 'dev' in cohort:
            for system in ('baseline', 'whisper', 'parakeet'):
                comparisons['router_vs_'+system] = paired_cluster_bootstrap([
                    {'group_id': refs[i['id']]['group_id'], 'baseline': counts[i['id']][system+'-raw'],
                        'candidate': counts[i['id']]['router-raw']} for i in selected], resamples=2000, seed=55)
        raw_text = {s: {'nonempty': sum(bool(hypotheses(i, refs[i['id']], results[i['id']])[s].strip()) for i in selected),
            'characters': sum(len(hypotheses(i, refs[i['id']], results[i['id']])[s]) for i in selected)}
            for s in hypotheses(selected[0], refs[selected[0]['id']], results[selected[0]['id']])}
        cohorts[cohort] = {'samples': len(selected), 'scores': aggregate, 'comparisons': comparisons,
            'raw_text': raw_text, 'reasons': dict(Counter(results[i['id']]['reason'] for i in selected))}
    def wer(cohort, model):
        return cohorts[cohort]['scores'][model+'-raw']['wer_lexical_corpus']
    checks = {'original_human_preserved': wer('partial_human_dev', 'router') <= wer('partial_human_dev', 'whisper'),
        'strong_noise_human_improved': wer('acoustic_5_partial_human_dev', 'router') < wer('acoustic_5_partial_human_dev', 'whisper'),
        'original_weak_preserved': wer('publisher_weak_dev', 'router') <= wer('publisher_weak_dev', 'whisper'),
        'EN_control': wer('general_clean', 'router') <= wer('general_clean', 'baseline')+.01,
        'RU_control': wer('general_ru', 'router') <= wer('general_ru', 'baseline')+.01}
    result = {'plan_sha256': file_hash(ROOT/'plan.json'), 'cohorts': cohorts, 'checks': checks,
        'diagnostic_status': 'INCONCLUSIVE' if all(checks.values()) else 'FAIL',
        'new_ASR_calls': 0, 'ASR_training_updates': 0, 'classifier_fits': 10,
        'classifier_training_rows': training['observations'], 'threshold': training['threshold'],
        'training_OOF': training['OOF'], 'quality_evidence': False, 'release_promoted': False,
        'blind_dev_accessed': False, 'test_accessed': False}
    save(ROOT/'comparison.json', result)
    save(ROOT/'scored-counts.json', counts)
    save(ROOT/'human-examples.json', examples)
    lines = ['# Выбор ASR по признакам сильного шума', '',
        'Переключатель обучен на 3927 обучающих звуковых вариантах без расшифровок. Порог выбран по train и зафиксирован до dev.',
        'Whisper — прежний v5 balanced. Все ASR-тексты переиспользованы; выполнена новая классификация звука.', '',
        '| Набор | Фрагментов | Baseline | Whisper | Parakeet | Переключатель |',
        '|---|---:|---:|---:|---:|---:|']
    for name, row in cohorts.items():
        if row['scores']['baseline-raw']['N']:
            values = [f'{row["scores"][s+"-raw"]["wer_lexical_corpus"]*100:.2f}%' if s+'-raw' in row['scores'] else '—'
                for s in ('baseline', 'whisper', 'parakeet', 'router')]
            lines.append('| '+name+' | '+str(row['samples'])+' | '+' | '.join(values)+' |')
    lines += ['', 'Неречевые входы без VAD, вставки/мин:', '',
        '| Набор | Baseline | Whisper | Parakeet | Переключатель |', '|---|---:|---:|---:|---:|']
    for name in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'):
        lines.append('| '+name+' | '+' | '.join(f'{cohorts[name]["scores"][s+"-raw"]["inserted_words_per_minute"]:.2f}'
            for s in ('baseline', 'whisper', 'parakeet', 'router'))+' |')
    lines += ['', 'Все записи, сырые непустые ответы, фиксированный VAD и групповые интервалы: comparison.json.',
        'Train и dev используют одинаковое семейство синтетических искажений, но разные записи/дикторов/seed. Это не подтверждает перенос на реальный незнакомый шум.',
        'Пять частичных ручных и 35 слабых dev прежние. Рабочая модель сохранена, SPEC не подтверждён.', '']
    (ROOT/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print({'checks': checks, 'WER': {c: r['scores']['router-raw']['wer_lexical_corpus'] for c, r in cohorts.items()}}, flush=True)


def verify():
    plan, items, results, training = records()
    data = np.load(ROOT/'io-train/features.npz')
    rows = read(ROOT/'io-train/feature-rows.json')
    count = 0
    for index, (row, features) in enumerate(training_rows(read(ROOT/'train-inputs.json'))):
        assert row == rows[index]
        np.testing.assert_array_equal(features, data['X'][index])
        assert row['label'] == data['y'][index] and row['reader'] == data['groups'][index]
        count += 1
    assert count == 3927
    assert set(f['held_reader'] for f in training['folds']) == set(data['groups'])
    for fold in training['folds']:
        assert fold['held_reader'] not in fold['train_readers']
        assert set(fold['train_readers']) == set(data['groups'])-{fold['held_reader']}
        assert fold['held_rows'] == int((data['groups'] == fold['held_reader']).sum())
    threshold = max(.8, float(np.quantile(data['oof'][data['y'] == 0], .99, method='higher')))
    assert threshold == training['threshold']
    model = joblib.load(ROOT/'io-train/router.joblib')
    assert len(model.estimators_) == 256 and model.n_features_in_ == 62
    refs, scores = read(ROOT/'scoring/references.json'), read(ROOT/'scored-counts.json')
    waveforms = distances = 0
    for item in items:
        row = results[item['id']]
        if item['language'] != 'en':
            expected = 'whisper'
        else:
            x = waveform(item)
            waveforms += 1
            if not item['parakeet'].strip():
                expected = 'parakeet'
            else:
                f = audio_features(x)
                np.testing.assert_array_equal(f, row['features'])
                p = float(model.predict_proba(f[None])[0, 1])
                assert abs(p-row['severe_probability']) < 1e-12
                expected = 'parakeet' if p >= threshold else 'whisper'
        assert expected == row['selected']
        a = lexical_normalizer_v1(refs[item['id']]['reference']).split()
        for system, text in hypotheses(item, refs[item['id']], row).items():
            b = lexical_normalizer_v1(text).split()
            c = scores[item['id']][system+'-raw']
            assert c['N'] == len(a) and c['S']+c['D']+c['I'] == Levenshtein.distance(a, b)
            distances += 1
    save(ROOT/'verification.json', {'status': 'PASS', 'plan_sha256': file_hash(ROOT/'plan.json'),
        'training_waveforms_and_features_replayed': count, 'OOF_reader_folds_checked': len(training['folds']),
        'training_threshold_replayed': threshold, 'routed_waveforms_replayed': waveforms,
        'decisions_replayed': len(items), 'independent_edit_totals': distances,
        'verifier_sha256': file_hash(Path(__file__))})
    print({'status': 'PASS', 'features_replayed': count, 'decisions_replayed': len(items), 'edit_totals': distances}, flush=True)
