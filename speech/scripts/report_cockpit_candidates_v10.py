"""Score the preregistered candidates; never import references into inference."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from cockpit_candidates_v10 import ROOT, pcm, read, save, validate, waveform
from rapidfuzz.distance import Levenshtein

from north55_speech.cockpit_candidates_v10 import compose_candidates, deep_filter, speech_present
from north55_speech.core import file_hash
from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    lexical_normalizer_v1,
    paired_cluster_bootstrap,
)


def records():
    plan = validate()
    assert file_hash(ROOT/'scoring/references.json') == plan['files_sha256']['scoring/references.json']
    items, refs = read(ROOT/'inputs.json'), read(ROOT/'scoring/references.json')
    prior = {r['id']: r for r in read(ROOT/'prior-decisions.json')}
    predictions = {}
    for system, folder in [('canary', 'io-canary'), ('dfn_parakeet', 'io-dfn')]:
        execution = read(ROOT/folder/'execution.json')
        assert execution['plan_sha256'] == file_hash(ROOT/'plan.json')
        assert execution['records'] == plan['planned_new_ASR_calls'][system]
        assert not execution['runtime_failures']
        rows = {}
        for name, digest in execution['prediction_sha256'].items():
            path = ROOT/folder/'predictions'/name
            assert file_hash(path) == digest
            row = read(path)
            assert row['plan_sha256'] == execution['plan_sha256'] and row['system'] == system
            assert not row['runtime_failure']
            rows[row['item']['id']] = row
        assert len(rows) == execution['records']
        predictions[system] = rows
    result = {}
    for item in items:
        identity = item['id']
        c, d = predictions['canary'].get(identity), predictions['dfn_parakeet'].get(identity)
        if item['language'] == 'en':
            assert c['item'] == item
        if d is not None:
            assert d['item'] == item
        result[identity] = compose_candidates(item, prior[identity], c['vad_keep'] if c else None,
            c['hypothesis'] if c else None, d['hypothesis'] if d else None)
    return plan, items, refs, predictions, result


def score():
    plan, items, refs, predictions, result = records()
    counts, examples = {}, []
    for item in items:
        identity = item['id']
        meta = refs[identity]
        counts[identity] = {}
        for name, text in result[identity].items():
            counts[identity][name+'-raw'] = edit_counts(meta['reference'], text)
            counts[identity][name+'-gate'] = edit_counts(meta['reference'], text if meta['vad_keep'] else '')
        if meta['cohort'] in ('partial_human_dev', 'acoustic_5_partial_human_dev'):
            examples.append({'id': identity, 'cohort': meta['cohort'], 'reference': meta['reference'],
                'hypotheses': result[identity], 'counts': counts[identity]})
    cohorts = {}
    for cohort in sorted({r['cohort'] for r in refs.values()}):
        selected = [i for i in items if refs[i['id']]['cohort'] == cohort]
        minutes = sum(i['duration_sec'] for i in selected)/60
        scores, comparisons, nonempty = {}, {}, {}
        for system in plan['systems']:
            nonempty[system] = sum(bool(result[i['id']][system].strip()) for i in selected)
            for mode in ('raw', 'gate'):
                key = system+'-'+mode
                scores[key] = corpus_counts([counts[i['id']][key] for i in selected])
                scores[key]['inserted_words_per_minute'] = scores[key]['I']/minutes
            if 'dev' in cohort and system != 'v9':
                comparisons[system+'_vs_v9'] = paired_cluster_bootstrap([
                    {'group_id': refs[i['id']]['group_id'], 'baseline': counts[i['id']]['v9-raw'],
                        'candidate': counts[i['id']][system+'-raw']} for i in selected],
                    resamples=2000, seed=55)
        cohorts[cohort] = {'samples': len(selected), 'scores': scores,
            'nonempty': nonempty, 'comparisons': comparisons}
    checks = {}
    target = ['partial_human_dev', 'publisher_weak_dev', 'quiet_human_dev',
        'acoustic_15_partial_human_dev', 'acoustic_15_publisher_weak_dev',
        'acoustic_5_partial_human_dev', 'acoustic_5_publisher_weak_dev']
    # Resolve quiet cohort spelling from the frozen input metadata, without changing membership.
    quiet = [c for c in cohorts if 'quiet' in c and 'human' in c]
    assert len(quiet) == 1
    target[2] = quiet[0]
    def wer(c, s):
        return cohorts[c]['scores'][s+'-raw']['wer_lexical_corpus']
    for system in plan['systems'][1:]:
        checks[system] = {'cockpit_cohorts_preserved': all(wer(c, system) <= wer(c, 'v9') for c in target),
            'at_least_one_cockpit_improved': any(wer(c, system) < wer(c, 'v9') for c in target),
            'EN_control': wer('general_clean', system) <= wer('general_clean', 'v9')+.01,
            'RU_control': wer('general_ru', system) == wer('general_ru', 'v9'),
            'raw_nonspeech_empty': all(cohorts[c]['nonempty'][system] == 0
                for c in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'))}
    truncated = [identity for identity, row in predictions['canary'].items() if row['token_limit_reached']]
    report = {'plan_sha256': file_hash(ROOT/'plan.json'), 'cohorts': cohorts, 'checks': checks,
        'diagnostic_pass': {s: all(v.values()) and not truncated for s, v in checks.items()},
        'canary_truncated_ids': truncated, 'new_ASR_calls': {'canary': 491, 'dfn_parakeet': 56},
        'references_changed': False, 'ASR_training_updates': 0,
        'independent_quality_acceptance': False, 'release_promoted': False,
        'blind_dev_accessed': False, 'test_accessed': False}
    save(ROOT/'comparison.json', report)
    save(ROOT/'scored-counts.json', counts)
    save(ROOT/'composed-predictions.json', result)
    save(ROOT/'human-examples.json', examples)
    systems = plan['systems']
    lines = ['# Canary-Qwen и DeepFilterNet3: фиксированное сравнение v10', '',
        'Прежние 541 вход; 491 новый ответ Canary и 56 новых ответов Parakeet после шумоподавления. Русские 50 ответов переиспользованы.',
        'Все параметры и правила выбора зафиксированы до dev. Ручные эталоны частичные, слабые эталоны не прошли ручную проверку.', '',
        '| Набор | n | '+' | '.join(systems)+' |', '|---|---:|'+'---:|'*len(systems)]
    for cohort, row in cohorts.items():
        if row['scores']['v9-raw']['N']:
            values = [f'{wer(cohort, s)*100:.2f}%' for s in systems]
            lines.append('| '+cohort+' | '+str(row['samples'])+' | '+' | '.join(values)+' |')
    lines += ['', 'Неречевые входы: число непустых сырых ответов.', '',
        '| Набор | '+' | '.join(systems)+' |', '|---|'+'---:|'*len(systems)]
    for cohort in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'):
        lines.append('| '+cohort+' | '+' | '.join(str(cohorts[cohort]['nonempty'][s]) for s in systems)+' |')
    lines += ['', 'canary_router использует Canary на несильном шуме и прежний Parakeet на сильном. dfn_parakeet использует шумоподавление только на 56 входах, ранее выбранных v9 по звуку.',
        'guarded_v9 сохраняет Whisper, если Parakeet пуст, но исходный фиксированный VAD обнаруживает речь. canary_guarded подавляет Canary только при пустом Parakeet и отсутствии речи по VAD.',
        'Групповые интервалы, режим с полным VAD и абсолютные ошибки: comparison.json. Это диагностика на уже использовавшемся dev, а не независимая приёмка SPEC.', '']
    (ROOT/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print({'diagnostic_pass': report['diagnostic_pass'], 'truncations': truncated,
        'human_WER': {c: {s: wer(c, s) for s in systems} for c in target if 'human' in c}}, flush=True)


def verify():
    plan, items, refs, predictions, result = records()
    scores, distances, checked = read(ROOT/'scored-counts.json'), 0, 0
    dfn_replays = 0
    assert read(ROOT/'composed-predictions.json') == result
    for item in items:
        identity = item['id']
        if item['language'] == 'en':
            x = waveform(item)
            checked += 1
            row = predictions['canary'][identity]
            assert speech_present(x) == row['vad_keep'] == refs[identity]['vad_keep']
            assert len(row['token_ids']) == row['generated_tokens']
            if identity in predictions['dfn_parakeet']:
                d = predictions['dfn_parakeet'][identity]
                path = ROOT/'io-dfn/audio'/(identity+'.wav')
                assert file_hash(path) == d['output_audio_sha256']
                y, rate = sf.read(path, dtype='float32')
                assert rate == 16000 and len(y) == len(x) and pcm(y) == d['output_pcm_sha256']
                assert d['denoising']['removed_delay_samples_48k'] == 1440
                assert d['denoising']['fresh_process_per_clip']
                if dfn_replays < 3:
                    replay, info = deep_filter(x, Path('/models/deep-filter'))
                    np.testing.assert_array_equal(replay, y)
                    assert info['output_samples_16k'] == len(x)
                    dfn_replays += 1
        a = lexical_normalizer_v1(refs[identity]['reference']).split()
        for system, text in result[identity].items():
            for mode in ('raw', 'gate'):
                b = lexical_normalizer_v1(text if mode == 'raw' or refs[identity]['vad_keep'] else '').split()
                c = scores[identity][system+'-'+mode]
                assert c['N'] == len(a) and c['S']+c['D']+c['I'] == Levenshtein.distance(a, b)
                distances += 1
    save(ROOT/'verification.json', {'status': 'PASS', 'plan_sha256': file_hash(ROOT/'plan.json'),
        'original_waveforms_and_VAD_checked': checked, 'decisions_checked': len(items),
        'independent_edit_totals': distances, 'denoised_waves_checked': 56,
        'denoiser_replays_exact': dfn_replays, 'new_GPU_ASR_calls': 547,
        'verifier_sha256': file_hash(Path(__file__))})
    print({'status': 'PASS', 'waves': checked, 'edit_totals': distances, 'DFN_replays': dfn_replays}, flush=True)
