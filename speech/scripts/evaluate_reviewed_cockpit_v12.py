"""Freeze user-reviewed dev references and evaluate fixed ASR profiles without tuning."""

import argparse
import json
import shutil
import time
from collections import Counter
from pathlib import Path

from north55_speech.core import atomic_json, confined, digest, file_hash, now
from north55_speech.metrics import edit_counts, lexical_normalizer_v1


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_new(path, value):
    if path.exists():
        raise ValueError('Preserve existing artifact: ' + str(path))
    atomic_json(path, value)


def freeze(workspace, packet, output, audio_root):
    from north55_speech.asr import local_model_manifest
    from north55_speech.datasets import load_manifest
    from north55_speech.schemas import PipelineConfig
    from scripts.materialize_reviewed_training import collect

    if output.exists():
        raise ValueError('Choose a new evaluation directory')
    strict, _, _ = collect(packet, 'asr')  # Includes revision checksum and immutable identity checks.
    strict_ids = {s.sample_id for s in strict if s.split == 'dev'}
    references, pending, inputs, sources = [], [], [], []
    for original in load_manifest(packet/'dev.jsonl'):
        paths = sorted((packet/'revisions'/original.sample_id).glob('revision-*.json'))
        if not paths:
            pending.append({'id': original.sample_id, 'reason': 'no_saved_human_transcript'})
            continue
        record = read(paths[-1])
        sample = type(original).model_validate(record['sample'])
        prov = sample.annotation_provenance
        if not (sample.split == 'dev' and sample.language == 'en'
                and sample.transcript_status == 'human_verified' and sample.reference_text
                and prov.get('reviewed_audio') is True and prov.get('annotator') == record['audit']['actor']
                and prov.get('verification_method') == 'identified_human_self_attestation'
                and 'transcript' in record['audit']['verified_tasks']
                and sample.rights_confirmed and sample.speech_origin == 'recorded_human'):
            pending.append({'id': original.sample_id, 'reason': 'incomplete_human_transcript_or_non_english'})
            continue
        if sample.unintelligible:
            raise ValueError('This scoring version requires a mask-aware extension before masked inputs')
        if digest(sample.model_dump()) != record['audit']['after_sha256']:
            raise ValueError('Revision changed')
        references.append(sample.model_dump(mode='json'))
        sources.append({'id': sample.sample_id, 'revision_path': str(paths[-1].relative_to(packet)),
                        'revision_sha256': file_hash(paths[-1]), 'strict': sample.sample_id in strict_ids})
        audio_path = confined(audio_root, sample.audio_path)
        if file_hash(audio_path) != sample.audio_sha256:
            raise ValueError('Audio changed')
        target = output/'audio'/f'{sample.sample_id}.wav'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(audio_path, target)
        inputs.append({'id': sample.sample_id, 'file': target.name,
                       'audio_sha256': sample.audio_sha256, 'duration_sec': sample.duration_sec})
    if not references:
        raise ValueError('No eligible reviewed English transcripts')
    save_new(output/'scoring/references.json', references)
    save_new(output/'inputs.json', inputs)
    # Keep exact annotation revisions and exposed draft provenance for future audit.
    for info in sources:
        dst = output/'scoring/revisions'/f"{info['id']}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(packet/info['revision_path'], dst)
    snapshot = output/'frozen'
    code_files = list((workspace/'src').rglob('*.py')) + [
        workspace/'scripts/evaluate_reviewed_cockpit_v12.py',
        workspace/'scripts/materialize_reviewed_training.py',
    ]
    code_hashes = {}
    for source in code_files:
        relative = source.relative_to(workspace)
        destination = snapshot/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        code_hashes[str(relative)] = file_hash(destination)
    config = PipelineConfig(model='small', device='cuda', compute_type='float16')
    plan = {'created_at': now(), 'purpose': 'fixed_model_diagnostic_on_user_reviewed_dev',
            'all_count': len(inputs), 'strict_ids': sorted(strict_ids & {x['id'] for x in inputs}),
            'strict_count': len(strict_ids & {x['id'] for x in inputs}), 'pending': pending,
            'seconds': sum(x['duration_sec'] for x in inputs),
            'source_revisions': sources, 'manifest_sha256': file_hash(packet/'dev.jsonl'),
            'inputs_sha256': file_hash(output/'inputs.json'),
            'references_sha256': file_hash(output/'scoring/references.json'),
            'code_sha256': code_hashes, 'baseline_config': config.model_dump(mode='json'),
            'baseline_model_manifest': local_model_manifest('small'),
            'hybrid_runtime_sha256': file_hash(workspace/'reports/cockpit-candidates-v10/local-runtime/runtime.json'),
            'consensus_runtime_sha256': file_hash(workspace/'reports/cockpit-consensus-v11/local-runtime/runtime.json'),
            'language_profile': 'en', 'normalizer': 'lexical_normalizer_v1',
            'comparisons': ['whisper_small', 'guarded_v9', 'consensus_v11'],
            'no_training_or_threshold_changes': True, 'test_accessed': False,
            'limitations': ['Machine-assisted human references, not blind independent transcription',
                'User-selected intelligible English subset; cannot generalize to skipped clips',
                f'{len(inputs)-len(strict_ids & {x["id"] for x in inputs})} missing scope confirmations remain unchanged; report strict subset separately',
                'Read cockpit scripts and few shared dev speakers; not operational cockpit acceptance']}
    save_new(output/'plan.json', plan)
    print(json.dumps({k: plan[k] for k in ['all_count', 'strict_count', 'seconds']}), flush=True)


def verify_code(plan):
    root = Path(__file__).resolve().parents[1]
    for relative, expected in plan['code_sha256'].items():
        if file_hash(root/relative) != expected:
            raise ValueError('Frozen evaluation code changed')


def baseline(study, output, audio_root):
    import soundfile as sf
    from north55_speech.asr import AsrProvider
    from north55_speech.schemas import PipelineConfig

    plan = read(study/'plan.json')
    verify_code(plan)
    if file_hash(study/'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Frozen inputs changed')
    if output.exists():
        raise ValueError('Preserve baseline output')
    provider = AsrProvider(PipelineConfig.model_validate(plan['baseline_config']))
    if provider.manifest != plan['baseline_model_manifest']:
        raise ValueError('Baseline model changed')
    started, records = time.perf_counter(), []
    for item in read(study/'inputs.json'):
        path = audio_root/item['file']
        if file_hash(path) != item['audio_sha256']:
            raise ValueError('Inference audio changed')
        x, rate = sf.read(path, dtype='float32')
        if rate != 16000 or x.ndim != 1 or abs(len(x)/rate-item['duration_sec']) > .001:
            raise ValueError('Inference audio contract mismatch')
        segments = provider.transcribe(x, 0, 'en', item['id'], lambda: None)
        records.append({'id': item['id'], 'input_sha256': item['audio_sha256'],
                        'hypothesis': ' '.join(s.raw_asr_text.strip() for s in segments),
                        'segments': [s.model_dump(mode='json') for s in segments]})
    save_new(output, {'plan_sha256': file_hash(study/'plan.json'), 'records': records,
                      'ASR_calls': len(records), 'seconds': time.perf_counter()-started,
                      'model': plan['baseline_config']['model'], 'device': provider.model.model.device})
    print(json.dumps({'baseline_calls': len(records)}), flush=True)


def distance(a, b):
    a, b = lexical_normalizer_v1(a).split(), lexical_normalizer_v1(b).split()
    previous = list(range(len(b)+1))
    for i, token in enumerate(a, 1):
        row = [i]
        for j, other in enumerate(b, 1):
            row.append(min(previous[j]+1, row[-1]+1, previous[j-1]+(token != other)))
        previous = row
    return previous[-1]


def score(study):
    plan = read(study/'plan.json')
    verify_code(plan)
    assert file_hash(study/'scoring/references.json') == plan['references_sha256']
    assert file_hash(study/'inputs.json') == plan['inputs_sha256']
    references = read(study/'scoring/references.json')
    inputs = {x['id']: x for x in read(study/'inputs.json')}
    raw, hybrid, consensus = [read(study/'io'/f'{name}.json') for name in ['baseline', 'hybrid', 'consensus']]
    assert raw['plan_sha256'] == file_hash(study/'plan.json')
    assert hybrid['runtime_sha256'] == plan['hybrid_runtime_sha256']
    assert consensus['runtime_sha256'] == plan['consensus_runtime_sha256']
    assert consensus['base_file_sha256'] == file_hash(study/'io/hybrid.json')
    predictions = {'whisper_small': {r['id']: r for r in raw['records']},
                   'guarded_v9': {Path(r['input_path']).stem: r for r in hybrid['records']},
                   'consensus_v11': {Path(r['input_path']).stem: r for r in consensus['records']}}
    for values in predictions.values():
        assert set(values) == set(inputs)
        assert all(values[key]['input_sha256'] == inputs[key]['audio_sha256'] for key in inputs)
    per_clip = []
    for ref in references:
        key = ref['sample_id']
        row = {'id': key, 'source': ref['annotation_provenance']['source_sample_id'],
               'strict': key in plan['strict_ids'], 'group': ref['group_id'], 'metrics': {}}
        for name, values in predictions.items():
            counts = edit_counts(ref['reference_text'], values[key]['hypothesis'])
            errors = sum(counts[k] for k in ['S', 'D', 'I'])
            assert errors == distance(ref['reference_text'], values[key]['hypothesis'])
            row['metrics'][name] = {k: counts[k] for k in ['S', 'D', 'I', 'N']}
        per_clip.append(row)
    summaries = {}
    for cohort, rows in [('all_transcript_verified', per_clip), ('scope_and_transcript_verified', [r for r in per_clip if r['strict']])]:
        summaries[cohort] = {'clips': len(rows), 'models': {}}
        for model in predictions:
            sums = {key: sum(r['metrics'][model][key] for r in rows) for key in ['S', 'D', 'I', 'N']}
            errors = sums['S']+sums['D']+sums['I']
            summaries[cohort]['models'][model] = {**sums, 'errors': errors, 'wer': errors/sums['N'] if sums['N'] else None}
    result = {'status': 'DIAGNOSTIC_ONLY', 'plan_sha256': file_hash(study/'plan.json'), 'cohorts': summaries,
              'speakers': len({speaker for r in references for speaker in r['speaker_ids']}),
              'recordings': len({r['recording_id'] for r in references}),
              'reference_methods': dict(Counter(r['annotation_provenance'].get('reference_method', 'unknown') for r in references)),
              'new_ASR_calls': raw['ASR_calls']+sum(consensus['actual_ASR_calls'].values()),
              'prediction_sha256': {name: file_hash(study/'io'/f'{name}.json') for name in ['baseline', 'hybrid', 'consensus']},
              'independent_edit_distance_checks': len(per_clip)*len(predictions),
              'per_clip': per_clip, 'limitations': plan['limitations'], 'test_accessed': False}
    save_new(study/'comparison.json', result)
    title = '# Проверка на новых человеческих расшифровках\n\n'
    text = title + f"Сохранено {len(references)} английских расшифровок, {plan['seconds']/60:.2f} минуты, {result['speakers']} диктора и {result['recordings']} исходных записей. Все тексты проверялись с машинным черновиком.\n\n"
    text += '| Модель | Все подтверждённые тексты: WER | Полностью подтверждённые: WER |\n|---|---:|---:|\n'
    labels = {'whisper_small': 'Исходный Whisper small', 'guarded_v9': 'Прежний профиль v9', 'consensus_v11': 'Согласованные правки v11'}
    for model, label in labels.items():
        columns = [summaries[c]['models'][model] for c in summaries]
        text += f"| {label} | " + ' | '.join(f"{m['wer']:.2%} ({m['errors']}/{m['N']})" for m in columns) + ' |\n'
    text += f"\nВ первом столбце {len(per_clip)} фрагментов, во втором {plan['strict_count']}. Отсутствующие подтверждения области и языка не проставлялись автоматически. Остальные {len(plan['pending'])} фрагментов не имеют подходящей сохранённой расшифровки; их качество здесь не оценено.\n\n"
    text += f"Выполнено {result['new_ASR_calls']} новых GPU ASR-вызовов. SHA-256 аудио, моделей/профилей, ревизий и результатов проверены; {result['independent_edit_distance_checks']} подсчётов ошибок сверены отдельным алгоритмом. Обучения и настройки по этим эталонам не было.\n\n"
    text += 'Это диагностический результат на отобранных пользователем разборчивых английских фрагментах. Он не доказывает качество на всей очереди, неразборчивой речи или новых дикторах. Машинная подсказка могла повлиять на человеческую расшифровку. Test не использовался.\n'
    with (study/'report.md').open('x', encoding='utf-8') as stream:
        stream.write(text)
    print(json.dumps({k: result[k] for k in ['cohorts', 'new_ASR_calls', 'speakers', 'recordings']}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'baseline', 'score'])
    parser.add_argument('--workspace', type=Path, default=Path('/workspace'))
    parser.add_argument('--packet', type=Path, default=Path('/packet'))
    parser.add_argument('--study', type=Path, default=Path('/study'))
    parser.add_argument('--output', type=Path, default=Path('/output'))
    parser.add_argument('--audio', type=Path, default=Path('/audio'))
    args = parser.parse_args()
    if args.stage == 'freeze':
        freeze(args.workspace, args.packet, args.output, args.audio)
    elif args.stage == 'baseline':
        baseline(args.study, args.output, args.audio)
    else:
        score(args.study)


if __name__ == '__main__':
    main()
