"""Build and evaluate complementary partitions of an existing NUS adapter."""

import argparse
import json
import shutil
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.lora_ablation import partition_adapter_state
from scripts.nus_failure_diagnosis import infer

ROOT = Path('/study')


def read(path):
    return json.loads(path.read_bytes())


def merge():
    import torch
    from ctranslate2.converters import TransformersConverter
    from peft import PeftModel
    from safetensors.torch import load_file, save_file
    from transformers import WhisperForConditionalGeneration

    torch.set_num_threads(4)
    plan = read(ROOT / 'build-plan.json')
    source = Path('/models/whisper-small-nus-v1')
    base = Path('/models/whisper-small-transformers')
    training = read(Path('/source/training.json'))
    if file_hash(Path('/source/training.json')) != plan['training_sha256']:
        raise ValueError('Source training record changed')
    for name, expected in plan['implementation_sha256'].items():
        if file_hash(Path('/app') / name) != expected:
            raise ValueError('Frozen implementation changed')
    # Check the complete base and adapter/tokenizer source against the original run.
    for name, expected in training['base_manifest']['files'].items():
        if file_hash(base / name) != expected:
            raise ValueError('Base weights changed')
    for name, expected in training['files'].items():
        if name.startswith(('adapter/', 'merged/')) and file_hash(source / name) != expected:
            raise ValueError('Saved trained adapter or merged source changed')
    original = load_file(source / 'adapter/adapter_model.safetensors')
    reports = {}
    for part in ('encoder', 'decoder'):
        out = Path('/models') / ('whisper-small-nus-' + part + '-v1')
        converted = Path(str(out) + '-ct2')
        if out.exists() or converted.exists():
            raise ValueError('Preserve existing model version')
        state, report = partition_adapter_state(original, part)
        (out / 'adapter').mkdir(parents=True)
        shutil.copyfile(source / 'adapter/adapter_config.json', out / 'adapter/adapter_config.json')
        save_file(state, out / 'adapter/adapter_model.safetensors')
        model = WhisperForConditionalGeneration.from_pretrained(str(base), local_files_only=True)
        adapted = PeftModel.from_pretrained(model, str(out / 'adapter'), local_files_only=True)
        merged = adapted.merge_and_unload()
        merged.save_pretrained(out / 'merged', safe_serialization=True)
        for p in (source / 'merged').iterdir():
            if p.is_file() and p.name not in ('config.json', 'generation_config.json') and p.suffix != '.safetensors':
                shutil.copyfile(p, out / 'merged' / p.name)
        converter = TransformersConverter(str(out / 'merged'), copy_files=['tokenizer.json', 'preprocessor_config.json'])
        converter.convert(str(converted), quantization='float16')
        manifest = {'model': converted.name, 'repo': 'local_lora_component_ablation',
                    'revision': file_hash(out / 'adapter/adapter_model.safetensors'),
                    'source_adapter_sha256': file_hash(source / 'adapter/adapter_model.safetensors'),
                    'source_training_sha256': plan['training_sha256'], 'kept_component': part,
                    'license': 'inherited_base_model_and_training_data_restrictions',
                    'quality_evidence': False, 'selection_allowed': False, 'training_steps': 0,
                    'files': {p.name: file_hash(p) for p in converted.iterdir() if p.is_file()}}
        atomic_json(converted / 'manifest.json', manifest)
        report.update(model=converted.name, manifest=manifest, manifest_sha256=file_hash(converted / 'manifest.json'),
                      adapter_sha256=file_hash(out / 'adapter/adapter_model.safetensors'))
        atomic_json(out / 'partition.json', report)
        reports[part] = report
        del model, adapted, merged, converter, state
        print(json.dumps({'part': part, 'zeroed_B_tensors': len(report['zeroed_B_tensors']), 'converted': converted.name}), flush=True)
    # Byte-for-byte source preservation after both merges, not an assumption.
    for name, expected in training['files'].items():
        if name.startswith(('adapter/', 'merged/')) and file_hash(source / name) != expected:
            raise ValueError('Source mutated during conversion')
    atomic_json(ROOT / 'partition.json', reports)
    models = plan['models'] | {part: {'name': report['model'], 'manifest': report['manifest'],
              'manifest_sha256': report['manifest_sha256']} for part, report in reports.items()}
    configs = plan['configs'] | {part + '_on': plan['configs']['nus_on'] | {'model': report['model']}
                                for part, report in reports.items()}
    atomic_json(ROOT / 'plan.json', {**plan, 'models': models, 'configs': configs,
                                   'partition_sha256': file_hash(ROOT / 'partition.json')})


def score():
    import scripts.score_nus_failure_diagnosis as scoring
    from north55_speech.metrics import paired_cluster_bootstrap
    from scripts.nus_failure_diagnosis import validate
    from scripts.research_audio_evidence import same_waveform, write_legacy_evidence
    from scripts.score_nus_failure_diagnosis import aggregate, load_records

    scoring.ROOT = ROOT
    plan = validate()
    if file_hash(ROOT / 'partition.json') != plan['partition_sha256']:
        raise ValueError('Partition evidence changed')
    for name, expected in plan['scoring_sha256'].items():
        if file_hash(ROOT / 'scoring' / name) != expected:
            raise ValueError('Frozen scoring material changed')
    refs = read(ROOT / 'scoring/references.json')
    inputs = read(ROOT / 'inputs.json')
    historical = {s: read(ROOT / 'scoring' / (s + '.json')) for s in ('parent_on', 'nus_on')}
    results, all_counts, checks = {}, {}, {}
    for stage, items in inputs.items():
        new = {p + '_on': load_records(stage, p + '_on', items, plan) for p in ('encoder', 'decoder')}
        lookup = new | historical
        checks[stage + '_runtime'] = all(r['runtime_failure'] is None for records in new.values() for r in records.values())
        checks[stage + '_same_options_and_audio'] = all(
            all(records[i['id']]['effective_options'] == historical['parent_on'][i['id']]['effective_options'] and
                same_waveform(i, records[i['id']], new['encoder_on'][i['id']]['effective_waveform_sha256'])
                for records in lookup.values()) for i in items)
        cohorts = {}
        for cohort in sorted({i['cohort'] for i in items}):
            members = [i for i in items if i['cohort'] == cohort]
            summary, counts = aggregate(members, refs, lookup)
            all_counts[cohort] = counts
            summary['comparisons'] = {}
            for part in ('encoder', 'decoder'):
                for base in ('parent', 'nus'):
                    a, b = (summary['scores'][s + '_on']['wer_lexical_corpus'] for s in (base, part))
                    value = {'wer_delta': b-a if a is not None and b is not None else None,
                             'relative_reduction': (a-b)/a if a else None}
                    if stage != 'fit':
                        value['bootstrap'] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                            'baseline': counts[base+'_on'][i['id']], 'candidate': counts[part+'_on'][i['id']]}
                            for i in members], resamples=2000, seed=55, confidence=.95)
                    summary['comparisons'][part + '_vs_' + base] = value
            if cohort in ('noise_only', 'bleriot_b_noise'):
                minutes = sum(i['duration_sec'] for i in members)/60
                summary['minutes'] = minutes
                summary['inserted_words_per_minute'] = {s: sum(v['I'] for v in counts[s].values())/minutes for s in lookup}
            cohorts[cohort] = summary
        results[stage] = cohorts
    for part in ('encoder', 'decoder'):
        records = load_records('control', part + '_on', inputs['control'][:1], plan, cpu=True)
        checks[part + '_CPU_smoke'] = all(r['runtime_failure'] is None for r in records.values())
    gates = {}
    for part in ('encoder', 'decoder'):
        control = results['control']
        comp = control['partial_human_dev']['comparisons'][part + '_vs_parent']
        checks_part = {'human_dev_point': comp['relative_reduction'] >= .10,
                      'clean_EN': control['general_clean']['comparisons'][part + '_vs_parent']['wer_delta'] <= .01,
                      'clean_RU': control['general_ru']['comparisons'][part + '_vs_parent']['wer_delta'] <= .01,
                      'noise': all(control[c]['inserted_words_per_minute'][part+'_on'] <=
                                   control[c]['inserted_words_per_minute']['parent_on'] for c in ('noise_only', 'bleriot_b_noise')),
                      'runtime': checks['control_runtime'] and checks['fit_runtime']}
        gates[part] = {k: 'PASS' if v else 'FAIL' for k, v in checks_part.items()} | {
            'statistical_confirmation': 'PASS' if comp['bootstrap']['upper'] < 0 else 'INCONCLUSIVE',
            'independent_ASR': 'NEEDS_MORE_DATA', 'critical_entities': 'NEEDS_MORE_DATA',
            'release': 'FAIL' if not all(checks_part.values()) else 'NEEDS_MORE_DATA'}
    result = {'artifact_status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks, 'cohorts': results,
              'gates': gates, 'new_training_steps': 0, 'new_GPU_predictions': 2*sum(map(len, inputs.values())),
              'scorer_script_sha256': file_hash(Path(__file__)),
              'new_CPU_predictions': 2, 'plan_sha256': file_hash(ROOT / 'plan.json'), 'test_accessed': False,
              'release_promoted': False, 'quality_evidence': False, 'fit_scope': 'Training-set fitting only; no quality CI.'}
    write_legacy_evidence(ROOT / 'legacy-waveform-evidence.json')
    atomic_json(ROOT / 'comparison.json', result)
    atomic_json(ROOT / 'scored-counts.json', all_counts)
    print(json.dumps({'artifact_status': result['artifact_status'], 'gates': gates,
                      'fit': results['fit'], 'human': results['control']['partial_human_dev']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('merge', 'fit', 'control', 'cpu', 'score'))
    parser.add_argument('part', nargs='?', choices=('encoder', 'decoder'))
    args = parser.parse_args()
    if args.stage == 'merge':
        merge()
    elif args.stage == 'score':
        score()
    else:
        if not args.part:
            parser.error('part is required')
        infer('control' if args.stage == 'cpu' else args.stage, args.part + '_on', cpu=args.stage == 'cpu')
