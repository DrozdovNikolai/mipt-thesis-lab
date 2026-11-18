"""Score a completed frozen selector and independently replay its decisions."""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import numpy as np
from rapidfuzz.distance import Levenshtein

from north55_speech.core import file_hash
from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    lexical_normalizer_v1,
    paired_cluster_bootstrap,
)
from scripts.cockpit_cross_asr_v6 import read, save
from scripts.cockpit_selector_v8 import ROOT, audio, validate


def records():
    plan = validate()
    assert file_hash(ROOT/'protocol.md') == plan['protocol_sha256']
    assert file_hash(ROOT/'scoring/references.json') == plan['references_sha256']
    assert file_hash(ROOT/'provenance.json') == plan['provenance_sha256']
    items = read(ROOT/'inputs.json')
    execution = read(ROOT/'io-gpu/execution.json')
    assert execution['plan_sha256'] == file_hash(ROOT/'plan.json')
    assert not execution['runtime_failures'] and execution['records'] == len(items) == 541
    assert execution['device'] == 'cuda' and execution['compute_type'] == 'float32'
    results = {}
    for item in items:
        path = ROOT/'io-gpu/predictions'/(item['id']+'.json')
        assert file_hash(path) == execution['prediction_sha256'][path.name]
        row = read(path)
        assert row['input'] == item and not row['runtime_failure']
        assert row['plan_sha256'] == execution['plan_sha256']
        assert row['hypothesis'] == item[row['selected']]
        results[item['id']] = row
    return plan, items, results, execution


def texts(item, meta, row):
    values = {'baseline': meta['baseline'], 'whisper': item['whisper'], 'selector': row['hypothesis']}
    if item['parakeet'] is not None:
        values['parakeet'] = item['parakeet']
    return values


def score():
    plan, items, results, execution = records()
    refs = read(ROOT/'scoring/references.json')
    counts, examples = {}, []
    for item in items:
        identity = item['id']
        meta, row = refs[identity], results[identity]
        values = texts(item, meta, row)
        counts[identity] = {}
        for name, text in values.items():
            counts[identity][name+'-raw'] = edit_counts(meta['reference'], text)
            counts[identity][name+'-gate'] = edit_counts(meta['reference'], text if meta['vad_keep'] else '')
        if meta['cohort'] == 'partial_human_dev':
            examples.append({'id': identity, 'reference': meta['reference'], 'hypotheses': values,
                'selected': row['selected'], 'reason': row['reason'], 'scores': row['scores'],
                'counts': counts[identity]})
    cohorts = {}
    for cohort in sorted({m['cohort'] for m in refs.values()}):
        selected = [i for i in items if refs[i['id']]['cohort'] == cohort]
        duration = sum(i['duration_sec'] for i in selected)/60
        aggregate = {}
        for name in counts[selected[0]['id']]:
            aggregate[name] = corpus_counts([counts[i['id']][name] for i in selected])
            aggregate[name]['inserted_words_per_minute'] = aggregate[name]['I']/duration
        comparisons = {}
        if 'dev' in cohort:
            for system in ('baseline', 'whisper', 'parakeet'):
                comparisons['selector_vs_'+system] = paired_cluster_bootstrap([
                    {'group_id': refs[i['id']]['group_id'], 'baseline': counts[i['id']][system+'-raw'],
                        'candidate': counts[i['id']]['selector-raw']} for i in selected], resamples=2000, seed=55)
        raw_text = {s: {'nonempty_responses': sum(bool(texts(i, refs[i['id']], results[i['id']])[s].strip()) for i in selected),
            'characters': sum(len(texts(i, refs[i['id']], results[i['id']])[s]) for i in selected)}
            for s in texts(selected[0], refs[selected[0]['id']], results[selected[0]['id']])}
        cohorts[cohort] = {'samples': len(selected), 'groups': len({refs[i['id']]['group_id'] for i in selected}),
            'scores': aggregate, 'comparisons': comparisons, 'raw_text': raw_text,
            'selected': dict(Counter(results[i['id']]['selected'] for i in selected)),
            'reasons': dict(Counter(results[i['id']]['reason'] for i in selected))}
    human = cohorts['partial_human_dev']
    checks = {'human_point': human['scores']['selector-raw']['wer_lexical_corpus'] <= .9*human['scores']['whisper-raw']['wer_lexical_corpus'],
        'human_CI': human['comparisons']['selector_vs_whisper']['upper'] < 0,
        'EN_control': cohorts['general_clean']['scores']['selector-raw']['wer_lexical_corpus'] <= cohorts['general_clean']['scores']['baseline-raw']['wer_lexical_corpus']+.01,
        'RU_control': cohorts['general_ru']['scores']['selector-raw']['wer_lexical_corpus'] <= cohorts['general_ru']['scores']['baseline-raw']['wer_lexical_corpus']+.01,
        'nonspeech_raw': all(cohorts[c]['scores']['selector-raw']['I'] <= cohorts[c]['scores']['baseline-raw']['I']
            for c in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'))}
    result = {'plan_sha256': file_hash(ROOT/'plan.json'), 'cohorts': cohorts, 'checks': checks,
        'diagnostic_status': 'NEEDS_MORE_DATA' if all(checks.values()) else 'FAIL',
        'new_ASR_calls': 0, 'new_training_updates': 0, 'GPU_rescoring': execution['totals'],
        'reused_ASR': plan['reused_ASR'], 'quality_evidence': False, 'release_promoted': False,
        'blind_dev_accessed': False, 'test_accessed': False}
    save(ROOT/'comparison.json', result)
    save(ROOT/'scored-counts.json', counts)
    save(ROOT/'human-examples.json', examples)
    lines = ['# Выбор между Whisper и Parakeet по оценке аудио', '',
        'Полная проверка фиксированного правила на 541 прежнем входе. Новых обучений и генераций ASR нет.',
        'Whisper — сохранённый v5 balanced. Вероятности текстов на аудио вычислены заново моделью medium.en.', '',
        '| Набор | Фрагментов | Baseline | Whisper | Parakeet | Выбор по аудио |',
        '|---|---:|---:|---:|---:|---:|']
    for name, row in cohorts.items():
        if not row['scores']['baseline-raw']['N']:
            continue
        values = [f'{row["scores"][s+"-raw"]["wer_lexical_corpus"]*100:.2f}%' if s+'-raw' in row['scores'] else '—'
            for s in ('baseline', 'whisper', 'parakeet', 'selector')]
        lines.append('| '+name+' | '+str(row['samples'])+' | '+' | '.join(values)+' |')
    lines += ['', 'Неречевые входы без VAD, вставленные слова/мин:', '',
        '| Набор | Baseline | Whisper | Parakeet | Выбор по аудио |', '|---|---:|---:|---:|---:|']
    for name in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'):
        lines.append('| '+name+' | '+' | '.join(f'{cohorts[name]["scores"][s+"-raw"]["inserted_words_per_minute"]:.2f}'
            for s in ('baseline', 'whisper', 'parakeet', 'selector'))+' |')
    lines += ['', 'Сырые символы/непустые ответы, все решения, отдельные результаты фиксированного VAD и групповые интервалы сохранены в comparison.json.',
        'Пять частично ручных эталонов и 35 слабых dev многократно исследовались. Их акустические копии не независимы. Train-fit не является оценкой переноса.',
        'Правило не обучалось по dev-эталонам, но идея возникла после изучения прежних результатов. Это диагностический опыт; SPEC не подтверждён.',
        'Новые blind-dev и закрытый test не использованы. Рабочая модель сохранена.', '']
    (ROOT/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print({'checks': checks, 'WER': {c: r['scores']['selector-raw']['wer_lexical_corpus'] for c, r in cohorts.items()}})


def verify():
    plan, items, results, execution = records()
    refs = read(ROOT/'scoring/references.json')
    scores = read(ROOT/'scored-counts.json')
    waveforms = distances = probabilities = 0
    for item in items:
        identity, row = item['id'], results[item['id']]
        if item['language'] == 'en':
            audio(item)
            waveforms += 1
        a = lexical_normalizer_v1(refs[identity]['reference']).split()
        for name, text in texts(item, refs[identity], row).items():
            b = lexical_normalizer_v1(text).split()
            c = scores[identity][name+'-raw']
            assert c['N'] == len(a) and c['S']+c['D']+c['I'] == Levenshtein.distance(a, b)
            distances += 1
        # Independently reconstruct the rule, including its shortcuts and mean-log score.
        if item['language'] != 'en':
            expected = 'whisper'
        elif not item['parakeet'].strip() or not item['whisper'].strip():
            expected = 'parakeet'
        elif lexical_normalizer_v1(item['whisper']) == lexical_normalizer_v1(item['parakeet']):
            expected = 'whisper'
        else:
            valid = {}
            for name, value in row['scores'].items():
                if value['mean_log_probability'] is None:
                    continue
                pp = np.asarray(value['token_probabilities'], dtype='float64')
                assert len(pp) == len(value['token_ids']) and np.isfinite(pp).all() and ((0 <= pp) & (pp <= 1)).all()
                computed = float(np.log(np.maximum(pp, 1e-30)).mean())
                assert math.isclose(computed, value['mean_log_probability'], abs_tol=1e-12)
                valid[name] = computed
                probabilities += len(pp)
            assert valid
            expected = next(iter(valid)) if len(valid) == 1 else ('parakeet' if valid['parakeet']-valid['whisper'] > .10 else 'whisper')
        assert expected == row['selected'] and row['hypothesis'] == item[expected]
    replays = {}
    for mode in ('cpu', 'replay'):
        e = read(ROOT/('io-'+mode)/'execution.json')
        assert e['records'] == 2 and not e['runtime_failures'] and e['plan_sha256'] == file_hash(ROOT/'plan.json')
        max_score_difference = 0.
        for name, digest in e['prediction_sha256'].items():
            path = ROOT/('io-'+mode)/'predictions'/name
            assert file_hash(path) == digest
            r = read(path)
            original = results[r['input']['id']]
            assert r['input'] == original['input'] and r['selected'] == original['selected']
            for system, value in r['scores'].items():
                other = original['scores'][system]
                assert value['token_ids'] == other['token_ids']
                delta = abs(value['mean_log_probability'] - other['mean_log_probability'])
                assert delta < (.01 if mode == 'cpu' else .00001)
                max_score_difference = max(max_score_difference, delta)
        replays[mode] = {'records': 2, 'same_selections': True, 'max_mean_log_probability_difference': max_score_difference,
            'device': e['device'], 'compute_type': e['compute_type'], 'calls': e['totals']}
    result = {'status': 'PASS', 'plan_sha256': file_hash(ROOT/'plan.json'), 'waveforms_verified': waveforms,
        'selection_decisions_replayed': len(items), 'independent_edit_totals': distances,
        'token_probabilities_reaggregated': probabilities, 'replays': replays,
        'new_ASR': 0, 'new_training_updates': 0, 'verifier_sha256': file_hash(Path(__file__))}
    save(ROOT/'verification.json', result)
    print(result)
