"""Score and independently verify the matched expanded-data experiment."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf
from rapidfuzz.distance import Levenshtein

from north55_speech.core import file_hash
from north55_speech.cross_data_adaptation import ARMS, balanced_schedule, expand_without_overlaps
from north55_speech.datasets import load_manifest
from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    lexical_normalizer_v1,
    paired_cluster_bootstrap,
)
from scripts.cockpit_data_v7 import EXP, ROOT, load_audio, pcm, read, save, validate


def records():
    plan = validate()
    assert file_hash(ROOT/'protocol.md') == plan['protocol_sha256']
    assert file_hash(ROOT/'scoring/references.json') == plan['references_sha256']
    assert file_hash(ROOT/'scoring/history.json') == plan['history_sha256']
    assert file_hash(ROOT/'scoring/vad.json') == plan['vad_sha256']
    items = read(ROOT/'inputs.json')
    history = read(ROOT/'scoring/history.json')
    by_system = {'baseline': history['baseline'], 'v5-balanced': history['balanced']}
    counts = {}
    for arm in ('baseline', *ARMS, *('cpu-'+a for a in ARMS)):
        execution = read(ROOT/('io-'+arm)/'execution.json')
        assert execution['plan_sha256'] == file_hash(ROOT/'plan.json') and not execution['runtime_failures']
        expected = 18 if arm == 'baseline' else 2 if arm.startswith('cpu-') else 559
        assert execution['records'] == expected
        assert execution['actual_device'] == ('cpu' if arm.startswith('cpu-') else 'cuda')
        rows = {}
        for name, digest in execution['prediction_sha256'].items():
            path = ROOT/('io-'+arm)/'predictions'/name
            assert file_hash(path) == digest
            row = read(path)
            assert not row['runtime_failure']
            assert row['plan_sha256'] == file_hash(ROOT/'plan.json')
            model_name = plan['baseline_model']['name'] if arm == 'baseline' else plan['model_names'][arm.removeprefix('cpu-')]
            assert row['config']['model'] == model_name
            rows[row['id']] = row
        if arm == 'baseline':
            assert not (set(rows) & set(by_system['baseline']))
            by_system['baseline'].update(rows)
        else:
            by_system[arm] = rows
        counts[arm] = execution['new_ASR_calls']
    for item in items:
        for arm in ('baseline', *ARMS):
            row = by_system[arm][item['id']]
            assert all(row.get(k) == v for k, v in item.items())
            assert row['effective_waveform_sha256'] == by_system['baseline'][item['id']]['effective_waveform_sha256']
            assert row['effective_options'] == by_system['baseline'][item['id']]['effective_options']
    return plan, items, by_system, counts


def score():
    plan, items, predictions, calls = records()
    refs = read(ROOT/'scoring/references.json')
    gates = {r['id']: r for r in read(ROOT/'scoring/vad.json')['rows']}
    assert len(gates) == 541
    scores, examples = {}, []
    for item in items:
        identity = item['id']
        scores[identity] = {}
        if identity in gates:
            assert gates[identity]['pcm_sha256'] == predictions['baseline'][identity]['effective_waveform_sha256']
        for arm in ('baseline', 'v5-balanced', *ARMS):
            if identity not in predictions[arm]:
                continue
            hypothesis = predictions[arm][identity]['hypothesis']
            scores[identity][arm+'-raw'] = edit_counts(refs[item['reference_id']], hypothesis)
            if identity in gates:
                text = hypothesis if gates[identity]['keep'] else ''
                scores[identity][arm+'-gate'] = edit_counts(refs[item['reference_id']], text)
        if item['cohort'] == 'partial_human_dev':
            examples.append({'id': identity, 'reference': refs[item['reference_id']],
                'hypotheses': {a: predictions[a][identity]['hypothesis'] for a in ('baseline', 'v5-balanced', *ARMS)},
                'scores': scores[identity]})
    cohorts = {}
    for cohort in sorted({i['cohort'] for i in items}):
        group = [i for i in items if i['cohort'] == cohort]
        keys = scores[group[0]['id']].keys()
        results = {}
        minutes = sum(i['duration_sec'] for i in group)/60
        for key in keys:
            results[key] = corpus_counts([scores[i['id']][key] for i in group])
            results[key]['inserted_words_per_minute'] = results[key]['I']/minutes
        comparisons = {}
        if 'dev' in cohort:
            for left in ('baseline', 'v5-balanced', 'control'):
                comparisons['expanded_vs_'+left] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                    'baseline': scores[i['id']][left+'-raw'], 'candidate': scores[i['id']]['expanded-raw']}
                    for i in group], resamples=2000, seed=55)
        cohorts[cohort] = {'samples': len(group), 'groups': len({i['group_id'] for i in group}),
            'scores': results, 'comparisons': comparisons}
    human = cohorts['partial_human_dev']['scores']
    control_errors = sum(human['control-raw'][k] for k in ('S', 'D', 'I'))
    expanded_errors = sum(human['expanded-raw'][k] for k in ('S', 'D', 'I'))
    checks = {'human_point_vs_control': expanded_errors <= .9*control_errors,
        'human_CI_vs_control': cohorts['partial_human_dev']['comparisons']['expanded_vs_control']['upper'] < 0,
        'general_EN_vs_baseline': cohorts['general_clean']['scores']['expanded-raw']['wer_lexical_corpus'] <= cohorts['general_clean']['scores']['baseline-raw']['wer_lexical_corpus']+.01,
        'general_RU_vs_baseline': cohorts['general_ru']['scores']['expanded-raw']['wer_lexical_corpus'] <= cohorts['general_ru']['scores']['baseline-raw']['wer_lexical_corpus']+.01,
        'noise_with_gate': all(cohorts[c]['scores']['expanded-gate']['I'] <= cohorts[c]['scores']['baseline-gate']['I'] for c in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'))}
    result = {'plan_sha256': file_hash(ROOT/'plan.json'), 'cohorts': cohorts, 'checks': checks,
        'new_GPU_ASR': sum(calls[a] for a in ('baseline', *ARMS)), 'new_CPU_ASR': sum(calls['cpu-'+a] for a in ARMS),
        'reused_baseline_ASR': 541, 'reused_v5_context_ASR': 541, 'quality_evidence': False,
        'release_promoted': False, 'test_accessed': False, 'blind_dev_accessed': False,
        'diagnostic_status': 'NEEDS_MORE_DATA' if all(checks.values()) else 'FAIL'}
    save(ROOT/'comparison.json', result)
    save(ROOT/'scored-counts.json', scores)
    save(ROOT/'human-examples.json', examples)
    lines = ['# Эффект новых слабых данных', '',
        'Два обучения по 240 обновлений: контроль 247 пар и расширенный набор 259 пар. Шесть старых коротких фрагментов заменены восемнадцатью новыми.',
        'Настройки, исходные веса, начальные адаптеры, типы акустических слотов и seed совпадают. Все тексты остаются слабыми.', '',
        '| Набор | Фрагментов | Baseline | v5 balanced | Свежий контроль | Новые данные |',
        '|---|---:|---:|---:|---:|---:|']
    for name, row in cohorts.items():
        if row['scores']['baseline-raw']['N']:
            values = [f'{row["scores"][a+"-raw"]["wer_lexical_corpus"]*100:.2f}%' if a+'-raw' in row['scores'] else '—'
                for a in ('baseline', 'v5-balanced', *ARMS)]
            lines.append('| '+name+' | '+str(row['samples'])+' | '+' | '.join(values)+' |')
    lines += ['', 'Неречевые входы, вставленные слова/мин без VAD:', '',
        '| Набор | Baseline | v5 balanced | Свежий контроль | Новые данные |', '|---|---:|---:|---:|---:|']
    for name in ('noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'):
        lines.append('| '+name+' | '+' | '.join(f'{cohorts[name]["scores"][a+"-raw"]["inserted_words_per_minute"]:.2f}' for a in ('baseline', 'v5-balanced', *ARMS))+' |')
    lines += ['', 'После одинакового фиксированного VAD все 60 неречевых контролей имеют ноль вставок; новые train-fit пробы VAD не оценивались.',
        'Старые частичные/слабые dev многократно использовались; новые искажённые версии не независимы. Проверка SPEC не подтверждена.',
        '1136 новых GPU ASR и 4 CPU ASR. Рабочая модель сохранена. Новый blind-dev и закрытый test не использованы.', '',
        'Метрики и групповые интервалы: comparison.json. Примеры: human-examples.json. Данные: data-audit.json. Проверка: verification.json.', '']
    (ROOT/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'checks': checks, 'human_errors': {'control': control_errors, 'expanded': expanded_errors},
        'WER': {c: {a: r['scores'][a+'-raw']['wer_lexical_corpus'] for a in ('control', 'expanded')} for c, r in cohorts.items()}}, indent=2), flush=True)


def verify():
    import torch
    from safetensors.torch import load_file
    from transformers import WhisperProcessor

    from north55_speech.robust_adaptation import augment_waveform

    # checks service mounts current code; validate frozen code explicitly, not through /app.
    plan = read(ROOT/'plan.json')
    for name, digest in plan['implementation_sha256'].items():
        assert file_hash(ROOT/'frozen'/name) == digest
    assert file_hash(ROOT/'schedule.json') == plan['schedule_sha256']
    data = ROOT/'datasets'
    for name, digest in plan['dataset_sha256'].items():
        assert file_hash(data/name) == digest
    old, expanded, union = (load_manifest(data/(s+'.jsonl')) for s in ('control', 'expanded', 'union'))
    old_ids = {s.sample_id for s in old}
    rebuilt, removed = expand_without_overlaps(old, [s for s in union if s.sample_id not in old_ids])
    assert [s.sample_id for s in rebuilt] == [s.sample_id for s in expanded]
    schedules = read(ROOT/'schedule.json')
    assert schedules == {'control': balanced_schedule(old), 'expanded': balanced_schedule(expanded)}
    samples = {s.sample_id: s for s in union}
    processor = WhisperProcessor.from_pretrained('/models/whisper-small-transformers', local_files_only=True)
    processor.tokenizer.set_prefix_tokens(language='en', task='transcribe')
    training = read(ROOT/'training.json')
    contracts = read(ROOT/'io-train/audio-contracts.json')
    assert file_hash(ROOT/'io-train/audio-contracts.json') == training['audio_contracts_sha256']
    assert training['plan_sha256'] == file_hash(ROOT/'plan.json')
    for entry in contracts:
        meta = entry['metadata']
        sample = samples[meta['parent']]
        x, rate = sf.read(Path('/audio')/sample.audio_path, dtype='float32')
        assert rate == 16000 and file_hash(Path('/audio')/sample.audio_path) == sample.audio_sha256
        if meta['augmented']:
            x, details = augment_waveform(x, meta['seed'])
            assert details == meta['augmentation']
        assert pcm(x) == entry['waveform_sha256'] and len(x) == entry['audio_samples']
        target = np.asarray([processor.tokenizer(sample.reference_text).input_ids[1:]], dtype=np.int64)
        assert hashlib.sha256(target.tobytes()).hexdigest() == entry['label_sha256']
    assert len({training['arms'][a]['initial_adapter_sha256'] for a in ARMS}) == 1
    for arm in ARMS:
        folder = EXP/'training'/('checkpoint-'+arm)
        for name, digest in training['checkpoints'][arm].items():
            assert file_hash(folder/name) == digest
        state = torch.load(folder/'optimizer.pt', map_location='cpu', weights_only=True)['state']
        assert len(state) == 96 and {int(s['step']) for s in state.values()} == {240}
        adapter = load_file(folder/'adapter_model.safetensors')
        assert len(adapter) == 96 and all('.decoder.' in name for name in adapter)
        assert all(torch.count_nonzero(value) for name, value in adapter.items() if 'lora_B' in name)
        expected = Counter((e['parent']+'@'+str(e['seed'])) if e['augmented'] else e['parent'] for e in schedules[arm])
        assert dict(expected) == training['arms'][arm]['coverage']
    conversion = read(ROOT/'conversion.json')
    for model in conversion['models'].values():
        for name, digest in model['files'].items():
            assert file_hash(EXP/'models'/model['model']/name) == digest
    # Independent edit totals for actual outputs; no use of report aggregation.
    refs, items = read(ROOT/'scoring/references.json'), read(ROOT/'inputs.json')
    scores = read(ROOT/'scored-counts.json')
    verified = 0
    for item in items:
        waveform = load_audio(item)
        for arm in ARMS:
            path = ROOT/('io-'+arm)/'predictions'/(item['id']+'.json')
            row = read(path)
            execution = read(ROOT/('io-'+arm)/'execution.json')
            assert file_hash(path) == execution['prediction_sha256'][path.name]
            assert pcm(waveform) == row['effective_waveform_sha256']
            a, b = (lexical_normalizer_v1(t).split() for t in (refs[item['reference_id']], row['hypothesis']))
            c = scores[item['id']][arm+'-raw']
            assert len(a) == c['N'] and Levenshtein.distance(a, b) == c['S']+c['D']+c['I']
            verified += 1
    result = {'status': 'PASS', 'real_updates_each': 240, 'optimizer_tensors_each': 96,
        'training_waveforms_and_labels_replayed': len(contracts), 'ASR_comparisons_replayed': verified,
        'old_rows': len(old), 'expanded_rows': len(expanded), 'contained_old_rows_replaced': len(removed),
        'plan_sha256': file_hash(ROOT/'plan.json'), 'verifier_sha256': file_hash(Path(__file__))}
    save(ROOT/'verification.json', result)
    print(json.dumps(result), flush=True)
