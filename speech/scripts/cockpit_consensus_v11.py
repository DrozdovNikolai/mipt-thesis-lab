"""Freeze, apply and evaluate two fixed consensus rules on completed ASR responses."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from north55_speech.cockpit_consensus_v11 import select_consensus
from north55_speech.core import file_hash
from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    lexical_normalizer_v1,
    paired_cluster_bootstrap,
)

ROOT = Path('/study')
SYSTEMS = ('base', 'utterance', 'edits')


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def prepare():
    work, old = Path('/workspace'), Path('/workspace/reports/cockpit-candidates-v10')
    assert not (ROOT/'plan.json').exists()
    assert read(old/'verification.json')['status'] == 'PASS'
    p10 = read(old/'plan.json')
    for name, digest in p10['files_sha256'].items():
        assert file_hash(old/name) == digest
    execution = read(old/'io-canary/execution.json')
    assert execution['plan_sha256'] == file_hash(old/'plan.json') and not execution['runtime_failures']
    composed = read(old/'composed-predictions.json')
    prior = {r['id']: r for r in read(old/'prior-decisions.json')}
    items = []
    for item in read(old/'inputs.json'):
        identity, canary = item['id'], None
        if item['language'] == 'en':
            path = old/'io-canary/predictions'/(identity+'.json')
            assert file_hash(path) == execution['prediction_sha256'][path.name]
            canary = read(path)['hypothesis']
        items.append({'id': identity, 'language': item['language'], 'duration_sec': item['duration_sec'],
            'pcm_sha256': item['pcm_sha256'], 'base': composed[identity]['guarded_v9'],
            'parakeet': item['parakeet'], 'canary': canary,
            'severe': prior[identity]['selected'] == 'parakeet' and bool(item['parakeet'] and item['parakeet'].strip())})
    save(ROOT/'inputs.json', items)
    save(ROOT/'scoring/references.json', read(old/'scoring/references.json'))
    save(ROOT/'scoring/base-counts.json', {k: {'raw': v['guarded_v9-raw'], 'gate': v['guarded_v9-gate']}
        for k, v in read(old/'scored-counts.json').items()})
    files = ['scripts/cockpit_consensus_v11.py', 'src/north55_speech/cockpit_consensus_v11.py',
        'src/north55_speech/metrics.py', 'src/north55_speech/core.py', 'src/north55_speech/__init__.py']
    for name in files:
        target = ROOT/'frozen'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work/name, target)
    plan = {'prior_plan_sha256': file_hash(old/'plan.json'), 'new_ASR_calls': 0, 'records': 541,
        'files_sha256': {n: file_hash(ROOT/n) for n in ('inputs.json', 'protocol.md',
            'scoring/references.json', 'scoring/base-counts.json')},
        'implementation_sha256': {n: file_hash(ROOT/'frozen'/n) for n in files},
        'selection_uses_references': False, 'blind_dev_accessed': False, 'test_accessed': False,
        'source_results': {n: file_hash(old/n) for n in ('composed-predictions.json',
            'scored-counts.json', 'comparison.json', 'verification.json', 'io-canary/execution.json')}}
    save(ROOT/'plan.json', plan)
    (ROOT/'io-infer').mkdir(exist_ok=True)
    for p in [ROOT, *ROOT.rglob('*')]:
        os.chown(p, 10001, 10001)
    print({'plan_sha256': file_hash(ROOT/'plan.json'), 'records': 541}, flush=True)


def validate():
    plan = read(ROOT/'plan.json')
    for name, digest in plan['implementation_sha256'].items():
        assert file_hash(Path('/app')/name) == digest
    for name in ('inputs.json', 'protocol.md'):
        assert file_hash(ROOT/name) == plan['files_sha256'][name]
    return plan


def infer():
    validate()
    rows = []
    for i in read(ROOT/'inputs.json'):
        rows.append({'id': i['id'], 'base': i['base'], **select_consensus(
            i['base'], i['parakeet'], i['canary'], i['language'], i['severe'])})
    save(Path('/output/decisions.json'), rows)
    save(Path('/output/execution.json'), {'plan_sha256': file_hash(ROOT/'plan.json'),
        'records': len(rows), 'new_ASR_calls': 0, 'decisions_sha256': file_hash(Path('/output/decisions.json')),
        'utterance_changes': sum(r['utterance_changed'] for r in rows),
        'edited_utterances': sum(bool(r['accepted_edits']) for r in rows),
        'edit_blocks': sum(len(r['accepted_edits']) for r in rows)})
    print({'records': len(rows), 'changes': sum(bool(r['accepted_edits']) for r in rows)}, flush=True)


def records():
    plan = validate()
    for name, digest in plan['files_sha256'].items():
        assert file_hash(ROOT/name) == digest
    execution = read(ROOT/'io-infer/execution.json')
    assert execution['plan_sha256'] == file_hash(ROOT/'plan.json')
    assert file_hash(ROOT/'io-infer/decisions.json') == execution['decisions_sha256']
    rows = {r['id']: r for r in read(ROOT/'io-infer/decisions.json')}
    items = read(ROOT/'inputs.json')
    assert len(rows) == len(items) == 541
    return plan, items, read(ROOT/'scoring/references.json'), rows


def score():
    _, items, refs, rows = records()
    counts, cohorts = {}, {}
    for item in items:
        identity = item['id']
        counts[identity] = {s+'-'+m: edit_counts(refs[identity]['reference'],
            rows[identity][s] if m == 'raw' or refs[identity]['vad_keep'] else '')
            for s in SYSTEMS for m in ('raw', 'gate')}
    for cohort in sorted({r['cohort'] for r in refs.values()}):
        selected = [i for i in items if refs[i['id']]['cohort'] == cohort]
        scores = {k: corpus_counts([counts[i['id']][k] for i in selected]) for k in counts[selected[0]['id']]}
        ci = {}
        if 'dev' in cohort:
            for s in ('utterance', 'edits'):
                ci[s] = paired_cluster_bootstrap([{'group_id': refs[i['id']]['group_id'],
                    'baseline': counts[i['id']]['base-raw'], 'candidate': counts[i['id']][s+'-raw']}
                    for i in selected], resamples=2000, seed=55)
        cohorts[cohort] = {'samples': len(selected), 'scores': scores, 'comparisons': ci,
            'nonempty': {s: sum(bool(rows[i['id']][s].strip()) for i in selected) for s in SYSTEMS},
            'changed': dict(Counter(s for i in selected for s in ('utterance', 'edits')
                if lexical_normalizer_v1(rows[i['id']][s]) != lexical_normalizer_v1(rows[i['id']]['base'])))}
    target = ['partial_human_dev', 'publisher_weak_dev', 'quiet_partial_human_dev',
        'acoustic_15_partial_human_dev', 'acoustic_15_publisher_weak_dev',
        'acoustic_5_partial_human_dev', 'acoustic_5_publisher_weak_dev']
    def wer(c, s):
        return cohorts[c]['scores'][s+'-raw']['wer_lexical_corpus']
    checks = {}
    for s in ('utterance', 'edits'):
        checks[s] = {'cockpit_preserved': all(wer(c, s) <= wer(c, 'base') for c in target),
            'cockpit_improved': any(wer(c, s) < wer(c, 'base') for c in target),
            'EN_control': wer('general_clean', s) <= wer('general_clean', 'base')+.01,
            'RU_control': wer('general_ru', s) == wer('general_ru', 'base'),
            'nonspeech_empty': all(cohorts[c]['nonempty'][s] == 0
                for c in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'))}
    result = {'plan_sha256': file_hash(ROOT/'plan.json'), 'cohorts': cohorts, 'checks': checks,
        'diagnostic_pass': {s: all(v.values()) for s, v in checks.items()},
        'independent_quality_acceptance': False, 'new_ASR_calls': 0, 'release_promoted': False}
    save(ROOT/'comparison.json', result)
    save(ROOT/'scored-counts.json', counts)
    lines = ['# Согласие ASR v11', '', 'База — v9 с защитой от пустого ответа. Новых распознаваний нет.', '',
        '| Набор | n | База | Совпадение целиком | Совпадающие правки |', '|---|---:|---:|---:|---:|']
    for c, r in cohorts.items():
        if r['scores']['base-raw']['N']:
            lines.append('| '+c+' | '+str(r['samples'])+' | '+' | '.join(f'{wer(c,s)*100:.2f}%' for s in SYSTEMS)+' |')
    lines += ['', 'Критерии, доверительные интервалы, изменения по срезам и неречевые входы: comparison.json.',
        'Использован прежний многократно просмотренный dev. Это exploratory диагностика; совпадение ASR не равно правильной разметке.', '']
    (ROOT/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print({'diagnostic_pass': result['diagnostic_pass'], 'checks': checks}, flush=True)


def verify():
    _, items, refs, rows = records()
    scores = read(ROOT/'scored-counts.json')
    old = read(ROOT/'scoring/base-counts.json')
    distances = 0
    for i in items:
        identity = i['id']
        expected = select_consensus(i['base'], i['parakeet'], i['canary'], i['language'], i['severe'])
        assert all(rows[identity][k] == v for k, v in expected.items())
        for mode in ('raw', 'gate'):
            assert scores[identity]['base-'+mode] == old[identity][mode]
        a = lexical_normalizer_v1(refs[identity]['reference']).split()
        for s in SYSTEMS:
            for mode in ('raw', 'gate'):
                b = lexical_normalizer_v1(rows[identity][s] if mode == 'raw' or refs[identity]['vad_keep'] else '').split()
                c = scores[identity][s+'-'+mode]
                assert c['N'] == len(a) and c['S']+c['D']+c['I'] == Levenshtein.distance(a, b)
                distances += 1
    save(ROOT/'verification.json', {'status': 'PASS', 'plan_sha256': file_hash(ROOT/'plan.json'),
        'decisions_replayed': len(items), 'independent_edit_totals': distances,
        'base_counts_match_v10': True, 'new_ASR_calls': 0})
    print({'status': 'PASS', 'decisions': len(items), 'distances': distances}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'infer', 'score', 'verify'])
    globals()[parser.parse_args().stage]()
