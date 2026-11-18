"""Score fixed raw/gated models and independently inspect saved training artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter

from north55_speech.core import file_hash
from north55_speech.metrics import corpus_counts, edit_counts, paired_cluster_bootstrap
from north55_speech.robust_adaptation import ARMS
from scripts.cockpit_robust_v5 import EXP, ROOT, load_audio, pcm, read, save_new, validate

NOISE = {'noise_only', 'bleriot_b_noise', 'synthetic_nonspeech'}
SYSTEMS = ['baseline', *ARMS]


def audit():
    import torch
    from safetensors.torch import load_file
    from transformers import WhisperTokenizerFast

    from north55_speech.robust_adaptation import augment_waveform, negative_waveform
    from scripts.nus_convergence import verify_files

    plan, training = validate(), read(ROOT/'training.json')
    verify_files(EXP/'models'/plan['model_names']['uniform'], read(ROOT/'conversion.json')['models']['uniform']['files'])
    if training['plan_sha256'] != file_hash(ROOT/'plan.json'):
        raise ValueError('Training identity differs')
    contracts = read(ROOT/'io-train/audio-contracts.json')
    if file_hash(ROOT/'io-train/audio-contracts.json') != training['audio_contracts_sha256']:
        raise ValueError('Audio contracts changed')
    items = {i['id']: i for i in read(ROOT/'inputs.json')}
    refs = read(ROOT/'scoring/references.json')
    tokenizer = WhisperTokenizerFast.from_pretrained('/models/whisper-small-transformers', local_files_only=True)
    tokenizer.set_prefix_tokens(language='en', task='transcribe')
    waves, variants = {}, Counter()
    for c in contracts:
        meta = c['metadata']
        if 'original_train_parent' in meta:
            parent = meta['original_train_parent']
            if parent not in waves:
                waves[parent] = load_audio(items['fit-'+parent])
            x = waves[parent]
            target = torch.tensor([tokenizer(refs['fit-'+parent]).input_ids[1:]])
            if 'snr_db' in meta:
                x, rebuilt = augment_waveform(x, meta['seed'])
                if any(meta[k] != v for k, v in rebuilt.items()):
                    raise ValueError('Augmentation metadata changed')
                variants['augmented'] += 1
            else:
                variants['original'] += 1
        else:
            index = int(c['key'].split('-')[-1])
            x, rebuilt = negative_waveform(meta['seed'], index)
            if meta != rebuilt:
                raise ValueError('Nonspeech source changed')
            target = torch.tensor([training['nonspeech_labels']])
            variants['negative'] += 1
        if pcm(x) != c['waveform_sha256'] or len(x) != c['audio_samples']:
            raise ValueError('Scheduled waveform does not reproduce')
        if hashlib.sha256(target.numpy().tobytes()).hexdigest() != c['label_sha256']:
            raise ValueError('Target differs from unchanged parent or nonspeech tokens')
    if dict(variants) != {'original': 247, 'augmented': 420, 'negative': 240}:
        raise ValueError('Training population count differs')
    initial, summary = set(), {}
    for arm in ARMS:
        a = training['arms'][arm]
        folder = EXP/'training'/('checkpoint-'+arm)
        verify_files(folder, training['checkpoints'][arm])
        state = torch.load(folder/'optimizer.pt', map_location='cpu', weights_only=True)['state']
        if len(state) != 96 or {int(s['step']) for s in state.values()} != {240}:
            raise ValueError('Optimizer did not perform claimed updates')
        tensors = load_file(folder/'adapter_model.safetensors')
        matrices = [t for n, t in tensors.items() if '.lora_B.' in n]
        if len(matrices) != 48 or any('.encoder.' in n for n in tensors) or not all(bool(t.abs().sum() > 0) for t in matrices):
            raise ValueError('Decoder adaptation missing or encoder adapted')
        initial.add(a['initial_adapter_sha256'])
        if sum(a['coverage'].values()) != a['speech_presentations']+a['negative_presentations']:
            raise ValueError('Presentation count differs')
        manifest = read(ROOT/'io-convert/conversions'/(arm+'.json'))['model']
        verify_files(EXP/'models'/manifest['model'], manifest['files'])
        if read(EXP/'models'/manifest['model']/'manifest.json') != manifest:
            raise ValueError('Converted model manifest changed')
        summary[arm] = {k: a[k] for k in ('actual_updates', 'speech_presentations', 'negative_presentations', 'encoder_unchanged', 'frozen_base_unchanged')}
    if len(initial) != 1 or training['arms']['balanced']['speech_schedule_sha256'] != training['arms']['balanced-silence']['speech_schedule_sha256']:
        raise ValueError('Matched initialization or speech schedule differs')
    result = {'status': 'PASS', 'waveforms_and_labels_reproduced': len(contracts), 'variants': dict(variants),
        'initial_adapters_identical': True, 'balanced_speech_schedules_identical': True, 'arms': summary,
        'plan_sha256': file_hash(ROOT/'plan.json')}
    save_new(ROOT/'model-data-verification.json', result)
    print(json.dumps(result, indent=2), flush=True)


def score():
    plan = validate()
    if file_hash(ROOT/'scoring/references.json') != plan['references_sha256']:
        raise ValueError('References changed')
    if read(ROOT/'model-data-verification.json')['status'] != 'PASS':
        raise ValueError('Missing checkpoint/data verification')
    refs, items = read(ROOT/'scoring/references.json'), read(ROOT/'inputs.json')
    vad = read(ROOT/'io-vad/vad.json')
    if vad['plan_sha256'] != file_hash(ROOT/'plan.json'):
        raise ValueError('VAD run differs')
    gates = {r['id']: r for r in vad['rows']}
    executions, counts, examples = {}, {}, []
    for system in SYSTEMS + ['cpu-'+a for a in ARMS]:
        e = read(ROOT/('io-'+system)/'execution.json')
        if e['plan_sha256'] != file_hash(ROOT/'plan.json') or e['runtime_failures']:
            raise ValueError('Incomplete or mismatched execution')
        if e['records'] != (2 if system.startswith('cpu-') else 541):
            raise ValueError('Incomplete execution coverage')
        if e['actual_device'] != ('cpu' if system.startswith('cpu-') else 'cuda'):
            raise ValueError('Execution device differs')
        expected_model = plan['baseline_model']['name'] if system == 'baseline' else plan['model_names'][system.removeprefix('cpu-')]
        for name, expected in e['prediction_sha256'].items():
            path = ROOT/('io-'+system)/'predictions'/name
            if file_hash(path) != expected or read(path)['config']['model'] != expected_model:
                raise ValueError('Prediction/model identity changed')
        executions[system] = e
    for item in items:
        records = {s: read(ROOT/('io-'+s)/'predictions'/(item['id']+'.json')) for s in SYSTEMS}
        gate = gates[item['id']]
        counts[item['id']] = {}
        for s, r in records.items():
            if any(r.get(k) != v for k, v in item.items()) or r['effective_waveform_sha256'] != gate['pcm_sha256']:
                raise ValueError('Comparison waveform/population differs')
            if r['effective_options'] != records['baseline']['effective_options']:
                raise ValueError('Comparison decoding options differ')
            for mode in ('raw', 'gate'):
                text = r['hypothesis'] if mode == 'raw' or gate['keep'] else ''
                counts[item['id']][s+'-'+mode] = edit_counts(refs[item['reference_id']], text)
        if item['cohort'] == 'partial_human_dev':
            examples.append({'id': item['id'], 'reference': refs[item['reference_id']],
                'hypotheses': {s: r['hypothesis'] for s, r in records.items()}, 'gate_keep': gate['keep'], 'counts': counts[item['id']]})
    cohorts = {}
    pairs = [('baseline', a) for a in ARMS] + [('uniform', 'balanced'), ('balanced', 'balanced-silence')]
    for cohort in sorted({i['cohort'] for i in items}):
        group = [i for i in items if i['cohort'] == cohort]
        minutes = sum(i['duration_sec'] for i in group)/60
        scores, comparisons = {}, {}
        for system in SYSTEMS:
            for mode in ('raw', 'gate'):
                key = system+'-'+mode
                scores[key] = corpus_counts([counts[i['id']][key] for i in group])
                scores[key]['inserted_words_per_minute'] = scores[key]['I']/minutes
        for left, right in pairs:
            for mode in ('raw', 'gate'):
                a, b = (scores[s+'-'+mode]['wer_lexical_corpus'] for s in (left, right))
                result = {'wer_delta': b-a if a is not None else None, 'relative_reduction': (a-b)/a if a else None}
                if 'dev' in cohort:
                    result['bootstrap'] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                        'baseline': counts[i['id']][left+'-'+mode], 'candidate': counts[i['id']][right+'-'+mode]} for i in group],
                        resamples=2000, seed=55, confidence=.95)
                comparisons[right+'_vs_'+left+'-'+mode] = result
        cohorts[cohort] = {'samples': len(group), 'groups': len({i['group_id'] for i in group}),
            'suppressed_inputs': sum(not gates[i['id']]['keep'] for i in group), 'scores': scores, 'comparisons': comparisons}
    checks = {}
    for arm in ARMS:
        for mode in ('raw', 'gate'):
            k = arm+'_vs_baseline-'+mode
            human = cohorts['partial_human_dev']['comparisons'][k]
            checks[arm+'-'+mode] = {'human_point': human['relative_reduction'] >= .1,
                'human_CI': human['bootstrap']['upper'] < 0,
                'general_EN': cohorts['general_clean']['comparisons'][k]['wer_delta'] <= .01,
                'general_RU': cohorts['general_ru']['comparisons'][k]['wer_delta'] <= .01,
                'noise': all(cohorts[c]['scores'][arm+'-'+mode]['I'] <= cohorts[c]['scores']['baseline-'+mode]['I'] for c in NOISE),
                'runtime': True}
    result = {'plan_sha256': file_hash(ROOT/'plan.json'), 'cohorts': cohorts, 'checks': checks,
        'diagnostic_status': 'NEEDS_MORE_DATA' if all(checks['balanced-silence-gate'].values()) else 'FAIL',
        'new_GPU_ASR': sum(executions[s]['new_ASR_calls'] for s in SYSTEMS),
        'reused_baseline_ASR': executions['baseline']['resumed'], 'CPU_ASR': 6,
        'quality_evidence': False, 'release_promoted': False, 'blind_dev_accessed': False, 'test_accessed': False}
    save_new(ROOT/'comparison.json', result)
    save_new(ROOT/'scored-counts.json', counts)
    save_new(ROOT/'scoring/human-examples.json', examples)
    report(result)
    print(json.dumps({'checks': checks, 'calls': result['new_GPU_ASR'], 'status': result['diagnostic_status']}, indent=2), flush=True)


def report(result):
    text = ['# Балансировка, акустические искажения и обучение молчанию', '',
        'Три обучения и все проверки завершены. Фиксированный кандидат: balanced-silence с прежним фильтром наличия речи.',
        '**Диагностический статус: '+result['diagnostic_status']+'**. Новая независимая ручная разметка не создавалась.', '',
        'Все три адаптера начинают с одинаковых весов, получают по 240 настоящих обновлений; энкодер и базовые веса неизменны.',
        'Uniform — прежние 247 пар и равномерный порядок; balanced — 960 речевых предъявлений с увеличенной долей сложных.',
        'В balanced: 480 чистых предъявлений, 420 различных шумовых версий с отражениями/громкостью/SpecAugment, 60 парных шумовых.',
        'Balanced-silence получает тот же речевой поток и дополнительно 240 синтетических неречевых примеров, вес loss 0.1.',
        'Неречевые цели: настоящий токен <|nocaptions|> и EOS. Синтетические варианты не добавляют новых голосов или человеческих текстов.', '',
        '## Распознавание', '', 'WER в процентах: raw / с фильтром речи. Меньше лучше.', '',
        '| Набор | N | Исходная | Uniform | Balanced | Balanced + silence |', '|---|---:|---:|---:|---:|---:|']
    for name, c in result['cohorts'].items():
        if name in NOISE:
            continue
        values = [' / '.join(f'{c["scores"][s+"-"+m]["wer_lexical_corpus"]*100:.2f}' for m in ('raw', 'gate')) for s in SYSTEMS]
        text.append(f'| {name} | {c["samples"]} | '+' | '.join(values)+' |')
    text += ['', '## Шум и фильтр', '', 'Ложные слова в минуту: raw / с фильтром.', '',
        '| Набор | Исходная | Uniform | Balanced | Balanced + silence |', '|---|---:|---:|---:|---:|']
    for name in sorted(NOISE):
        c = result['cohorts'][name]
        values = [' / '.join(f'{c["scores"][s+"-"+m]["inserted_words_per_minute"]:.2f}' for m in ('raw', 'gate')) for s in SYSTEMS]
        text.append('| '+name+' | '+' | '.join(values)+' |')
    text += ['', 'Количество входов, отсечённых одинаковым VAD, по наборам:', '',
        '`'+json.dumps({c: r['suppressed_inputs'] for c, r in result['cohorts'].items()}, ensure_ascii=False)+'`', '',
        '## Проверка и ограничения', '',
        f'{result["new_GPU_ASR"]} новых GPU-распознаваний, {result["reused_baseline_ASR"]} прежних baseline-ответов с проверкой хешей, 6 CPU-запусков.',
        'Фактические состояния AdamW проверены в сохранённых файлах. Все 907 входных сигналов обучения и их цели воспроизведены независимо.',
        'Фильтр фиксирован до опыта: VAD threshold 0.5, minimum speech 100 ms; при наличии речи окно сохраняется целиком.',
        'Новые 80 акустических dev-версий наследуют прежние тексты и группы. Это испытание на искажениях, а не независимые записи.',
        'Прежние 5 частично ручных и 35 слабых dev уже использовались многократно; групп всего 3 и 2 соответственно.',
        'Точечные изменения и групповые интервалы сохранены в comparison.json. Train-строки измеряют подгонку к слабым текстам.',
        'Новые 42 blind-dev и sealed test не открывались. Рабочая модель и прежние эксперименты не изменены.', '',
        'Диагностические проверки: `'+json.dumps(result['checks'], ensure_ascii=False)+'`.', '',
        '## Артефакты', '',
        'Протокол: protocol.md; зафиксированный код: frozen/; план: plan.json; порядок обучения: schedule.json.',
        'Модели: Docker volume `north55-speech_cockpit_robust_v5`, каталог `models/whisper-small-cockpit-robust-v5-{uniform,balanced,balanced-silence}`.',
        'Команды: `python -m scripts.run_cockpit_robust_v5 STAGE [ARM]`. Изменять завершённый опыт для нового обучения нельзя.', '']
    (ROOT/'report.md').write_text('\n'.join(text), encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['score', 'audit'])
    a = p.parse_args()
    {'score': score, 'audit': audit}[a.stage]()
