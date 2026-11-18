"""Post-hoc, hash-checked speech-gate composition; no new ASR or training."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from north55_speech.metrics import corpus_counts, edit_counts


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path('/app/reports')
    old, run, out = root / 'improvement-v1', root / 'cockpit-training-v4', Path('/output')
    plan, previous = read(run / 'plan.json'), read(old / 'inference/plan.json')
    assert sha(run / 'inputs.json') == plan['inputs_sha256']
    assert sha(run / 'scoring/references.json') == plan['references_sha256']
    assert previous['gate'] == {'threshold': .5, 'min_speech_duration_ms': 100}
    items = [i for i in read(run / 'inputs.json') if not i['cohort'].startswith('train_')]
    assert len(items) == 194
    refs, original = read(run / 'scoring/references.json'), read(run / 'comparison.json')
    systems = ['baseline', 'decoder-kl', 'decoder-ce', 'full-ce']
    execution = {s: read(run / ('io-' + s) / 'execution.json') for s in systems}
    vad_execution = read(old / 'predictions/small/execution.json')
    assert vad_execution['plan_sha256'] == sha(old / 'inference/plan.json')
    provenance, counts, decisions = {}, {}, []
    for i in items:
        old_id = 'bleriot-' + i['id'][5:] if i['id'].startswith('weak-') else i['id']
        cached_path = old / 'predictions/small' / (old_id + '.json')
        assert sha(cached_path) == vad_execution['files'][old_id]
        cached = read(cached_path)
        assert cached['plan_sha256'] == vad_execution['plan_sha256']
        keep = bool(cached['speech_intervals'])
        provenance[str(cached_path.relative_to(root))] = sha(cached_path)
        counts[i['id']] = {}
        for system in systems:
            p = run / ('io-' + system) / 'predictions' / (i['id'] + '.json')
            assert sha(p) == execution[system]['prediction_sha256'][p.name]
            r = read(p)
            assert r['plan_sha256'] == sha(run / 'plan.json') and r['runtime_failure'] is None
            assert r['effective_waveform_sha256'] == cached['pcm_sha256']
            provenance[str(p.relative_to(root))] = sha(p)
            for mode, text in [('raw', r['hypothesis']), ('gate', r['hypothesis'] if keep else '')]:
                counts[i['id']][system + '-' + mode] = edit_counts(refs[i['reference_id']], text)
        decisions.append({'id': i['id'], 'cohort': i['cohort'], 'retain_audio': keep,
                          'pcm_sha256': cached['pcm_sha256']})
    cohorts = {}
    for cohort in sorted({i['cohort'] for i in items}):
        selected = [i for i in items if i['cohort'] == cohort]
        minutes = sum(i['duration_sec'] for i in selected) / 60
        scores = {}
        for system in systems:
            for mode in ('raw', 'gate'):
                key = system + '-' + mode
                total = corpus_counts([counts[i['id']][key] for i in selected])
                if mode == 'raw':
                    assert total == original['cohorts'][cohort]['scores'][system]
                scores[key] = total | {'inserted_words_per_minute': total['I'] / minutes}
        cohorts[cohort] = {'samples': len(selected), 'scores': scores,
                          'suppressed_inputs': sum(not d['retain_audio'] for d in decisions if d['cohort'] == cohort)}
    result = {'status': 'PASS', 'analysis': 'post_hoc_exact_waveform_gate_composition',
              'controls': len(items), 'model_prediction_checks': len(items) * len(systems),
              'new_ASR_calls': 0, 'new_VAD_calls': 0, 'new_training_updates': 0,
              'new_human_labels': 0, 'blind_dev_accessed': False, 'test_accessed': False,
              'release_promoted': False, 'independent_quality_confirmation': False,
              'fixed_gate': previous['gate'], 'cohorts': cohorts}
    provenance |= {'cockpit-training-v4/plan.json': sha(run / 'plan.json'),
                   'cockpit-training-v4/scoring/references.json': sha(run / 'scoring/references.json'),
                   'improvement-v1/inference/plan.json': sha(old / 'inference/plan.json'),
                   'analysis_script': sha(Path(__file__))}
    text = ['# Проверка фильтра наличия речи с новыми адаптерами', '',
            'Проверены 194 прежних контроля и 776 сохранённых ответов моделей. Новых ASR-вызовов и обучения нет.',
            'Использован прежний фиксированный VAD: threshold 0.5, minimum speech 100 ms.',
            'При наличии речи исходное окно и ответ сохраняются целиком; при отсутствии ответ пустой.',
            'Сохранённые VAD-решения соответствуют побайтно тем же декодированным аудиосигналам.',
            'Это композиция сохранённых результатов после просмотра прошлого опыта, без замены рабочей модели.', '',
            '| Набор | N | Отсечено | Baseline raw/gate | Decoder+KL raw/gate | Decoder CE raw/gate | Full CE raw/gate |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for name, c in cohorts.items():
        noise = name in ('noise_only', 'bleriot_b_noise')
        metric = 'inserted_words_per_minute' if noise else 'wer_lexical_corpus'
        factor = 1 if noise else 100
        values = [' / '.join(f'{c["scores"][s + "-" + m][metric] * factor:.2f}' for m in ('raw', 'gate')) for s in systems]
        text.append(f'| {name} | {c["samples"]} | {c["suppressed_inputs"]} | ' + ' | '.join(values) + ' |')
    text += ['', 'Речевые строки: WER в процентах; шумовые: вставленные слова в минуту.',
             'Фильтр удаляет все 40 шумовых входов и сохраняет все 154 речевых, включая 14 тихих версий.',
             'Он устраняет измеренные вставки на этих шумах, но не исправляет ошибки внутри произнесённых команд.',
             'Пять частично ручных и 35 слабых кабинных эталонов остаются прежними и уже просмотренными.',
             'Новые 42 blind-dev не открывались. За пределами этих контролей ошибки VAD, включая пропуски тихой речи, не исключены.',
             'Преимущество распознавания кабинной речи на независимых данных этим расчётом не подтверждено.', '']
    out.mkdir(parents=True, exist_ok=True)
    for name, value in [('result.json', result), ('sources.json', provenance), ('gate-decisions.json', decisions)]:
        encoded = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
        p = out / name
        if p.exists():
            assert p.read_text(encoding='utf-8') == encoded, 'Preserve earlier diagnostic output'
        else:
            p.write_text(encoded, encoding='utf-8')
    (out / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    print('\n'.join(text), flush=True)


if __name__ == '__main__':
    main()
