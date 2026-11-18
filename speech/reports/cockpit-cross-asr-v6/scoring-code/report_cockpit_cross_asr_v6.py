"""Score the fixed cross-family diagnostic and audit weak labels/noisy pairs."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from north55_speech.core import file_hash
from north55_speech.datasets import Sample, validate_groups, write_manifest
from north55_speech.metrics import (
    canonical_normalizer_v1,
    corpus_counts,
    edit_counts,
    paired_cluster_bootstrap,
)
from scripts.cockpit_cross_asr_rules_v6 import compatible, decision, interval_union_seconds
from scripts.cockpit_cross_asr_v6 import EXP, STUDY, SYSTEMS, WORK, pcm, read, save
from scripts.expand_publisher_pairs import FAMILIES
from scripts.publisher_recovery_rules_v3 import normalize


def spectral_stats(x):
    power = np.abs(np.fft.rfft(x))**2
    frequencies = np.fft.rfftfreq(len(x), 1/16000)
    total = max(float(power.sum()), 1e-30)
    return {'rms_dbfs': 20*math.log10(max(float(np.sqrt(np.mean(x.astype('float64')**2))), 1e-15)),
        'peak': float(np.max(np.abs(x))), 'clip_fraction': float(np.mean(np.abs(x) >= .999)),
        'power_below_300Hz': float(power[frequencies < 300].sum()/total),
        'power_300_to_3400Hz': float(power[(frequencies >= 300) & (frequencies <= 3400)].sum()/total)}


def noise_audit(inputs, train, history, predictions, gates):
    by_id, train_ids = {i['id']: i for i in inputs}, {s['sample_id']: s for s in train}
    pairs = []
    for noisy in train:
        if not noisy['variant_of']:
            continue
        parent = train_ids[noisy['variant_of']]
        left, right = ('fit-'+s['sample_id'] for s in (parent, noisy))
        assert parent['reference_text'] == noisy['reference_text']
        x, xr = sf.read(EXP/by_id[left]['audio_path'], dtype='float32')
        y, yr = sf.read(EXP/by_id[right]['audio_path'], dtype='float32')
        assert xr == yr == 16000 and len(x) == len(y)
        assert pcm(x) == by_id[left]['pcm_sha256'] and pcm(y) == by_id[right]['pcm_sha256']
        a, b = x.astype('float64')-x.mean(), y.astype('float64')-y.mean()
        corr = signal.correlate(b, a, mode='full', method='fft')
        lags = signal.correlation_lags(len(b), len(a), mode='full')
        mask = np.abs(lags) <= 4000
        peak_index = np.argmax(np.abs(corr[mask]))
        denom = max(float(np.linalg.norm(a)*np.linalg.norm(b)), 1e-30)
        pairs.append({'id': right, 'clean_id': left, 'duration_sec': len(x)/16000,
            'same_weak_text': True, 'clean': spectral_stats(x), 'noisy': spectral_stats(y),
            'correlation_zero_lag': float(np.dot(a, b)/denom),
            'best_lag_sec_within_250ms': float(lags[mask][peak_index]/16000),
            'best_abs_correlation_within_250ms': float(abs(corr[mask][peak_index])/denom),
            'prior_coherence': noisy['annotation_provenance']['local_coherence'],
            'vad_keep': gates[right]['keep'], 'reference': noisy['reference_text'],
            'hypotheses': {s: history[right][s]['hypothesis'] for s in SYSTEMS} | {'parakeet': predictions[right]['hypothesis']},
            'clean_hypotheses': {s: history[left][s]['hypothesis'] for s in SYSTEMS} | {'parakeet': predictions[left]['hypothesis']}})
    override = {}
    for system in SYSTEMS:
        groups = defaultdict(lambda: {'records': 0, 'emitted_segments': 0, 'high_nospeech_overridden_segments': 0,
            'overridden_words': 0, 'total_words': 0, 'examples': []})
        for item in inputs:
            if item['id'] not in history:
                continue
            row = history[item['id']][system]
            cohort = item['cohort']
            stats = groups[cohort]
            stats['records'] += 1
            options = row['effective_options']
            for seg in row['segments']:
                stats['emitted_segments'] += 1
                words = len(seg['text'].split())
                stats['total_words'] += words
                if (options.get('no_speech_threshold') is not None and options.get('log_prob_threshold') is not None
                        and seg['no_speech_prob'] > options['no_speech_threshold']
                        and seg['avg_logprob'] > options['log_prob_threshold']):
                    stats['high_nospeech_overridden_segments'] += 1
                    stats['overridden_words'] += words
                    if len(stats['examples']) < 3:
                        stats['examples'].append({'id': item['id'], 'text': seg['text'],
                            'no_speech_prob': seg['no_speech_prob'], 'avg_logprob': seg['avg_logprob']})
        override[system] = dict(groups)
    save(STUDY/'noise-audit.json', {'pairs': pairs, 'emitted_segment_override': override,
        'interpretation': 'Correlation and VAD rejection are diagnostics, not proof of absent speech. Override counts describe emitted segments only.'})


def recovery(plan, predictions, train):
    disputed = read(STUDY/'scoring/disputed.json')
    sources, documents = read(STUDY/'scoring/sources.json'), read(STUDY/'scoring/documents.json')
    decisions, recovered = [], []
    original_intervals = defaultdict(list)
    for row in train:
        if row['variant_of']:
            continue
        p = row['annotation_provenance']
        original_intervals[p['source_sample_id']].append((p['original_start_sec'], p['original_end_sec']))
    proposed_intervals = defaultdict(list)
    for identity, old in disputed.items():
        item = old['item']
        docs = {k: v for k, v in documents.items() if Path(k).stem in FAMILIES[item['family']]}
        result = decision(predictions[identity], {'medium': old['medium'], 'large': old['large']},
            docs, item['duration_sec'], plan['recovery_policy'])
        result.update(id=identity, source=item['source'], prior_reasons=old['old_decision']['reasons'])
        decisions.append(result)
        if not result['accepted']:
            continue
        source = sources[item['source']]
        assert source['split'] == 'train'
        sample_id = hashlib.sha256(('cross-asr-v6:'+item['id']).encode()).hexdigest()[:32]
        row = {**source, 'sample_id': sample_id, 'audio_path': item['audio_path'],
            'audio_sha256': item['audio_sha256'], 'decoded_audio_sha256': None,
            'duration_sec': item['duration_sec'], 'channel': 0, 'variant_of': None, 'group_id': None,
            'original_utterance_id': source['original_utterance_id']+'@cross-asr-v6:'+item['id'],
            'language': 'en', 'input_language': 'en', 'scope': 'read_cockpit', 'scope_verified': False,
            'primary': False, 'clean_control': False, 'continuous_recording': False,
            'reference_text': result['target'], 'transcript_status': 'weak',
            'annotation_provenance': {'method': 'cross_family_consensus_v6', 'human_verified': False,
                'reviewed_audio': False, 'annotator': None, 'automatic_training_eligible': True,
                'source_sample_id': source['sample_id'], 'source_audio_sha256': source['audio_sha256'],
                'original_start_sec': item['original_start_sec'], 'original_end_sec': item['original_end_sec'],
                'target_origin': 'unprompted_parakeet_tdt_v2', 'supporting_teachers': result['supporting_teachers'],
                'publisher_support': result['publisher'], 'selection_plan_sha256': file_hash(STUDY/'inference/plan.json'),
                'parakeet_prediction_sha256': file_hash(STUDY/'predictions'/(identity+'.json'))}}
        recovered.append(Sample.model_validate(row))
        proposed_intervals[item['source']].append((item['original_start_sec'], item['original_end_sec']))
    original = [Sample.model_validate(row) for row in train]
    all_samples = [s.model_copy(deep=True, update={'group_id': None}) for s in original+recovered]
    validate_groups(all_samples)
    recovered_ids = {s.sample_id for s in recovered}
    recovered = [s for s in all_samples if s.sample_id in recovered_ids]
    output = STUDY/'datasets'
    output.mkdir(exist_ok=True)
    if (output/'supplemental-weak-train.jsonl').exists():
        raise ValueError('Preserve previous recovery')
    write_manifest(output/'supplemental-weak-train.jsonl', recovered)
    # This combined manifest is a proposal, not an instruction to retrain or count overlaps twice.
    write_manifest(output/'combined-weak-train.jsonl', all_samples)
    prior_seconds = sum(interval_union_seconds(v) for v in original_intervals.values())
    combined_seconds = sum(interval_union_seconds(original_intervals[k]+proposed_intervals[k])
        for k in set(original_intervals) | set(proposed_intervals))
    result = {'rejected_rechecked': len(disputed), 'accepted_weak': len(recovered),
        'summed_supplemental_seconds': sum(s.duration_sec for s in recovered),
        'supplemental_union_seconds': sum(interval_union_seconds(v) for v in proposed_intervals.values()),
        'prior_clean_union_seconds': prior_seconds, 'combined_clean_union_seconds': combined_seconds,
        'net_new_source_seconds': combined_seconds-prior_seconds,
        'sources': dict(Counter(s.annotation_provenance['source_sample_id'] for s in recovered)),
        'reasons': dict(Counter(r for d in decisions if not d['accepted'] for r in d['reasons'])),
        'human_verified': False, 'training_executed': False}
    save(STUDY/'recovery-decisions.json', decisions)
    save(STUDY/'recovery-summary.json', result)
    audit = []
    for row in train:
        identity = 'fit-'+row['sample_id']
        target, hypothesis = row['reference_text'], predictions[identity]['hypothesis']
        audit.append({'id': identity, 'paired_noise': bool(row['variant_of']), 'reference': target,
            'parakeet': hypothesis, 'cross_family_compatible': compatible(target, hypothesis, plan['recovery_policy']),
            'normalized_disagreement': edit_counts(normalize(target), normalize(hypothesis)),
            'source': row['annotation_provenance']['source_sample_id']})
    save(STUDY/'existing-label-audit.json', audit)
    return result


def score():
    plan = read(STUDY/'inference/plan.json')
    assert plan['protocol_sha256'] == file_hash(STUDY/'protocol.md')
    for name, digest in plan['scoring_sha256'].items():
        assert file_hash(STUDY/'scoring'/name) == digest
    for name, digest in plan['implementation_sha256'].items():
        assert file_hash(STUDY/'frozen'/name) == digest
    assert file_hash(STUDY/'inference/inputs.json') == plan['inputs_sha256']
    execution = read(STUDY/'predictions/execution.json')
    assert execution['plan_sha256'] == file_hash(STUDY/'inference/plan.json')
    assert not execution['failures'] and execution['records'] == 843 and execution['precision'] == 'torch.float32'
    inputs = read(STUDY/'inference/inputs.json')
    refs, history = read(STUDY/'scoring/references.json'), read(STUDY/'scoring/historical.json')
    gates = read(STUDY/'scoring/gates.json')
    predictions = {}
    for item in inputs:
        path = STUDY/'predictions'/(item['id']+'.json')
        assert file_hash(path) == execution['prediction_sha256'][path.name]
        row = read(path)
        assert not row['error'] and all(row.get(k) == v for k, v in item.items())
        predictions[item['id']] = row
    scores, examples = {}, []
    systems = (*SYSTEMS, 'parakeet')
    for item in inputs:
        identity = item['id']
        if identity not in refs:
            continue
        hypotheses = {s: history[identity][s]['hypothesis'] for s in SYSTEMS} | {'parakeet': predictions[identity]['hypothesis']}
        scores[identity] = {}
        for system, hypothesis in hypotheses.items():
            for mode in ('raw', 'gate'):
                text = hypothesis if mode == 'raw' or gates[identity]['keep'] else ''
                scores[identity][system+'-'+mode] = edit_counts(refs[identity], text)
            scores[identity][system+'-canonical'] = edit_counts(canonical_normalizer_v1(refs[identity]), canonical_normalizer_v1(hypothesis))
        if item['cohort'] == 'partial_human_dev':
            examples.append({'id': identity, 'reference': refs[identity], 'hypotheses': hypotheses, 'scores': scores[identity]})
    cohorts = {}
    for cohort in sorted({i['cohort'] for i in inputs if i['id'] in refs}):
        group = [i for i in inputs if i['cohort'] == cohort]
        minutes = sum(i['duration_sec'] for i in group)/60
        results = {}
        for system in systems:
            for mode in ('raw', 'gate', 'canonical'):
                key = system+'-'+mode
                result = corpus_counts([scores[i['id']][key] for i in group])
                results[key] = result | {'inserted_words_per_minute': result['I']/minutes}
        bootstrap = {}
        if 'dev' in cohort:
            for system in ('baseline', 'balanced'):
                bootstrap[system] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                    'baseline': scores[i['id']][system+'-raw'], 'candidate': scores[i['id']]['parakeet-raw']}
                    for i in group], resamples=2000, seed=55)
        cohorts[cohort] = {'samples': len(group), 'groups': len({i['group_id'] for i in group}),
            'results': results, 'parakeet_vs': bootstrap, 'gate_skips': sum(not gates[i['id']]['keep'] for i in group)}
    train = read(STUDY/'scoring/train.json')
    recovered = recovery(plan, predictions, train)
    noise_audit(inputs, train, history, predictions, gates)
    result = {'cohorts': cohorts, 'recovery': recovered, 'new_ASR': execution['records'],
        'quality_evidence': False, 'release_promoted': False, 'test_accessed': False, 'blind_dev_accessed': False,
        'plan_sha256': file_hash(STUDY/'inference/plan.json'), 'execution_sha256': file_hash(STUDY/'predictions/execution.json'),
        'scorer_sha256': file_hash(Path(__file__))}
    save(STUDY/'comparison.json', result)
    save(STUDY/'scored-counts.json', scores)
    save(STUDY/'human-examples.json', examples)
    lines = ['# Сравнение с Parakeet', '',
        '843 локальных GPU-распознавания: 491 прежний контроль/train-fit и все 352 отклонённых train-кандидата.',
        'Аудио идентично предыдущему опыту. Ниже lexical WER; меньше лучше. Все кабинные эталоны прежние, частичные или слабые.', '',
        '| Набор | N | Whisper small | uniform | balanced | + silence | Parakeet |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name, cohort in cohorts.items():
        if cohort['results']['baseline-raw']['N']:
            values = [f'{100*cohort["results"][s+"-raw"]["wer_lexical_corpus"]:.2f}%' for s in systems]
            lines.append('| '+name+' | '+str(cohort['samples'])+' | '+' | '.join(values)+' |')
    lines += ['', 'Неречевые входы, вставленные слова в минуту без VAD:', '',
        '| Набор | Whisper small | uniform | balanced | + silence | Parakeet |', '|---|---:|---:|---:|---:|---:|']
    for name in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'):
        lines.append('| '+name+' | '+' | '.join(f'{cohorts[name]["results"][s+"-raw"]["inserted_words_per_minute"]:.2f}' for s in systems)+' |')
    lines += ['', f'Восстановлено {recovered["accepted_weak"]} слабых фрагментов из 352: '
        f'{recovered["summed_supplemental_seconds"]/60:.2f} мин суммарно, '
        f'{recovered["net_new_source_seconds"]/60:.2f} мин нового покрытия сверх прежнего train после учёта перекрытий.', '',
        'Эти тексты не стали ручными эталонами. combined-weak-train.jsonl — предложение для следующего опыта; обучение не запускалось.',
        'Подробности: comparison.json, human-examples.json, recovery-decisions.json, existing-label-audit.json, noise-audit.json.',
        'Симметричная числовая нормализация сохранена как вторичная метрика. Она не заменяет lexical WER.',
        'Рабочая модель не заменялась; новые blind-dev и закрытый test не использованы.', '']
    (STUDY/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'recovery': recovered, 'cohort_WER': {k: v['results']['parakeet-raw']['wer_lexical_corpus'] for k, v in cohorts.items()}}, indent=2), flush=True)


if __name__ == '__main__':
    score()
