"""Fixed, offline two-arm retraining. Reference-free inference is mounted separately."""
import argparse
import json
from collections import Counter
from pathlib import Path

from north55_speech.asr import local_model_manifest
from north55_speech.core import atomic_json, file_hash, now, settings
from north55_speech.datasets import decoded_audio_hash, load_manifest, write_manifest
from north55_speech.lora import train_asr, validate_references
from scripts import language_large_experiment as engine
from scripts.assemble_quality_pairs import checked_groups

STUDY = Path('/study')
DATA = Path('/dataset')
EVAL = Path('/eval')
ARMS = ('control', 'augmented')
MODELS = {'parent': 'whisper-small-publisher-base-ct2',
          **{arm: f'whisper-small-retraining-v1-{arm}-ct2' for arm in ARMS}}
EXPECTED = {
    'SPEC.md': '9191d785add8109b4a3edd75171fab81987aac5df34036cb34daecbbe4de644f',
    'SOURCES.md': '74e70ac86c48d423f9a3da3d3d6bd8a13ee32cab6e537502ba0f12c3a939f114',
    'ACCEPTANCE.yaml': '32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071',
    'configs/baseline.yaml': '419accafb0874a51c11bd4865117a4daf761345a48242e36269c71e88a73e1d1',
}


def read(path):
    return json.loads(path.read_bytes())


def identity():
    return engine.identity() | {'retraining_script_sha256': file_hash(Path(__file__)),
        'admission_sha256': file_hash(Path('/app/src/north55_speech/retraining.py'))}


def config(arm):
    return {'train_manifest': f'/dataset/{arm}/train.jsonl', 'dev_manifest': '/dataset/dev.jsonl',
        'base_model': 'whisper-small-transformers', 'output': f'whisper-small-retraining-v1-{arm}',
        'reference_policy': 'mixed_sources_exploratory_v1', 'quality_evidence': False,
        'selection_allowed': False, 'rank': 8, 'max_steps': 120, 'eval_steps': 120, 'learning_rate': .0001}


def prepare():
    if (STUDY / 'plan.json').exists():
        raise ValueError('Training study already frozen')
    for name, expected in EXPECTED.items():
        if file_hash(Path('/app') / name) != expected:
            raise ValueError(f'Original contract changed: {name}')
    weak_path, support_path, dev_path = Path('/old/train.jsonl'), Path('/support/train.jsonl'), Path('/old/dev.jsonl')
    if file_hash(support_path) != '1f5726dee1572a3970b84afbd9914a9f5135ca8325005e6a756ef8b6284259ad':
        raise ValueError('Previously prepared support changed')
    if file_hash(dev_path) != '76fbf9ba6c29f31aeeff27d0cf0013638a76ab95e3d6a21b2d62f88a4e5384f6':
        raise ValueError('Previously frozen dev changed')
    weak, support, dev = map(load_manifest, (weak_path, support_path, dev_path))
    if len(weak) != 33 or len(dev) != 35 or Counter(s.language for s in support) != {'en': 200, 'ru': 200}:
        raise ValueError('Predeclared data composition changed')
    DATA.mkdir(exist_ok=True)
    (DATA / 'dev.jsonl').write_bytes(dev_path.read_bytes())
    data = {}
    for arm, rows in [('control', weak), ('augmented', weak + support)]:
        rows = [s.model_copy(deep=True) for s in rows]
        groups = checked_groups(rows, dev)
        validate_references(rows, dev, config(arm))
        for s in rows + dev:
            path = settings.audio_root / s.audio_path
            if file_hash(path) != s.audio_sha256 or decoded_audio_hash([path]) != s.decoded_audio_sha256:
                raise ValueError(f'Training audio changed: {s.sample_id}')
        path = DATA / arm / 'train.jsonl'
        write_manifest(path, rows)
        data[arm] = {'pairs': len(rows), 'minutes': sum(s.duration_sec for s in rows)/60,
            'languages': dict(Counter(s.language for s in rows)), 'groups': groups,
            'train_sha256': file_hash(path), 'dev_sha256': file_hash(DATA / 'dev.jsonl')}
    inputs = read(Path('/input-source.json'))
    previous = read(Path('/previous-plan.json'))
    if file_hash(Path('/input-source.json')) != previous['inputs_sha256'] or len(inputs) != 661:
        raise ValueError('Diagnostic input population changed')
    # Waveform check extends beyond the 35 training-validation clips, without loading answers.
    training_pcm = {s.decoded_audio_sha256 for s in weak + support}
    for item in inputs:
        path = settings.audio_root / item['audio_path']
        if file_hash(path) != item['audio_sha256'] or decoded_audio_hash([path]) in training_pcm:
            raise ValueError('Diagnostic audio changed or duplicates training audio')
    atomic_json(STUDY / 'inputs.json', inputs)
    base = read(settings.model_root / 'whisper-small-transformers/manifest.json')
    parent = local_model_manifest(MODELS['parent'])
    if parent['source_manifest_sha256'] != file_hash(settings.model_root / 'whisper-small-transformers/manifest.json'):
        raise ValueError('Converted parent is not the training base')
    plan = {'frozen_at': now().isoformat(), **identity(), 'configs': {a: config(a) for a in ARMS},
        'data': data, 'models': MODELS, 'base_manifest': base, 'parent_manifest': parent,
        'protocol_sha256': file_hash(STUDY / 'protocol.md'),
        'source_manifests': {'weak_train': file_hash(weak_path), 'support_train': file_hash(support_path),
                             'weak_dev': file_hash(dev_path)},
        'inputs_sha256': file_hash(STUDY / 'inputs.json'), 'references_sha256': previous['references_sha256'],
        'inference_template': previous['configs']['small_known'],
        'prior_plan_sha256': file_hash(Path('/previous-plan.json')),
        'budget': {'prior_development_configurations': 16, 'additional_fixed_training_arms': 2,
                   'total_cumulative_configurations': 18, 'steps_per_arm': 120, 'adaptive_trials': 0,
                   'authorization': 'user: так переобучай; SPEC section 362'},
        'test_accessed': False, 'selection_allowed': False, 'release_promoted': False,
        'limitations': previous['limitations'] + [
            'Supplement contains 2 known EN speakers and one conservative RU train group; RU individual IDs unavailable.',
            'Publisher train/dev speaker partition for FLEURS is inherited, not independently audited.',
            'Equal optimizer steps do not mean equal epochs or equal cockpit-example exposure.',
            'Only 5 partial human cockpit dev references, no independent final-test or complete critical entities.',
            'Monolingual EN and RU training does not validate mixed-language or spontaneous cockpit speech.']}
    atomic_json(STUDY / 'plan.json', plan)
    print(json.dumps({'status': 'FROZEN', 'data': data, 'budget': plan['budget']}, indent=2))


def validate_training():
    plan = read(STUDY / 'plan.json')
    if any(plan[k] != v for k, v in identity().items()) or file_hash(STUDY / 'protocol.md') != plan['protocol_sha256']:
        raise ValueError('Frozen training code or protocol changed')
    for arm in ARMS:
        if config(arm) != plan['configs'][arm] or file_hash(DATA / arm / 'train.jsonl') != plan['data'][arm]['train_sha256']:
            raise ValueError('Frozen training configuration or data changed')
    if file_hash(DATA / 'dev.jsonl') != plan['data']['control']['dev_sha256']:
        raise ValueError('Frozen dev changed')
    if read(settings.model_root / 'whisper-small-transformers/manifest.json') != plan['base_manifest']:
        raise ValueError('Frozen base changed')
    return plan


def train(arm):
    plan = validate_training()
    result = train_asr(plan['configs'][arm])
    atomic_json(STUDY / f'{arm}-training.json', result)
    c = result['training_coverage']
    if c['unique_samples_loaded'] != plan['data'][arm]['pairs'] or c['global_optimizer_steps'] != 120:
        raise ValueError('Training did not cover all declared samples and steps')
    print(json.dumps({'arm': arm, 'coverage': c, 'train_metrics': result['train_metrics'],
                      'dev_metrics': result['dev_metrics'], 'converted_inference': result['converted_inference']}, indent=2))


def freeze_eval():
    plan = validate_training()
    root = STUDY / 'evaluation'
    if (root / 'plan.json').exists():
        raise ValueError('Evaluation already frozen')
    manifests = {s: {'name': m, 'manifest': local_model_manifest(m),
                    'manifest_sha256': file_hash(settings.model_root / m / 'manifest.json')} for s, m in MODELS.items()}
    for arm in ARMS:
        trained = read(STUDY / f'{arm}-training.json')
        if (trained['base_manifest'] != plan['base_manifest'] or trained['config'] != plan['configs'][arm]
                or trained['converted_model'] != manifests[arm]['manifest']
                or trained['training_coverage']['global_optimizer_steps'] != 120
                or trained['training_coverage']['unique_samples_loaded'] != plan['data'][arm]['pairs']):
            raise ValueError('Saved trained model does not match fixed experiment')
    if manifests['parent']['manifest'] != plan['parent_manifest']:
        raise ValueError('Parent changed')
    root.mkdir(exist_ok=True)
    (root / 'inputs.json').write_bytes((STUDY / 'inputs.json').read_bytes())
    (root / 'protocol.md').write_bytes((STUDY / 'protocol.md').read_bytes())
    atomic_json(root / 'plan.json', {**identity(), 'frozen_at': now().isoformat(),
        'configs': {s: plan['inference_template'] | {'model': m} for s, m in MODELS.items()},
        'models': manifests, 'systems': list(MODELS), 'input_count': 661,
        'inputs_sha256': plan['inputs_sha256'], 'references_sha256': plan['references_sha256'],
        'training_plan_sha256': file_hash(STUDY / 'plan.json'),
        'protocol_sha256': file_hash(root / 'protocol.md'), 'limitations': plan['limitations'],
        'test_accessed': False, 'release_promoted': False})
    print(json.dumps({'status': 'EVALUATION_FROZEN', 'systems': list(MODELS), 'inputs': 661}))


def validate_eval():
    engine.ROOT = EVAL
    plan = engine.validate()
    if any(plan[k] != v for k, v in identity().items()):
        raise ValueError('Frozen retraining driver changed')
    return plan


def infer(system):
    plan = validate_eval()
    model = plan['models'][system]
    if (file_hash(settings.model_root / model['name'] / 'manifest.json') != model['manifest_sha256']
            or local_model_manifest(model['name']) != model['manifest']):
        raise ValueError('Frozen inference weights changed')
    engine.infer(system)


def score():
    from north55_speech.metrics import (
        corpus_counts,
        edit_counts,
        lexical_normalizer_v1,
        paired_cluster_bootstrap,
    )

    plan = validate_eval()
    ref_path = Path('/scoring/references.json')
    if file_hash(ref_path) != plan['references_sha256']:
        raise ValueError('Frozen scorer references changed')
    refs, items = read(ref_path), read(EVAL / 'inputs.json')
    rows, lookup = [], {}
    for system in MODELS:
        execution = read(EVAL / system / 'execution.json')
        if execution['plan_sha256'] != file_hash(EVAL / 'plan.json') or len(execution['prediction_sha256']) != len(items):
            raise ValueError('Incomplete inference population')
        for item in items:
            path = EVAL / system / 'predictions' / f'{item["id"]}.json'
            if file_hash(path) != execution['prediction_sha256'][path.name]:
                raise ValueError('Frozen prediction changed')
            r = read(path)
            if r['runtime_failure'] is not None and r['hypothesis']:
                raise ValueError('Failure must be scored as an empty hypothesis')
            row = {**r, 'reference': refs[item['id']],
                   'score': edit_counts(refs[item['id']], r['hypothesis']) if refs[item['id']] is not None else None}
            rows.append(row)
            lookup[system, item['id']] = row
    cohorts = {}
    for cohort in sorted({i['cohort'] for i in items}):
        selected = [i for i in items if i['cohort'] == cohort]
        eligible = [i for i in selected if refs[i['id']] is not None]
        scores = {s: corpus_counts([lookup[s, i['id']]['score'] for i in eligible]) for s in MODELS}
        comparisons = {}
        for name, a, b in [('control_vs_parent', 'parent', 'control'),
                           ('augmented_vs_parent', 'parent', 'augmented'),
                           ('augmented_vs_control', 'control', 'augmented')]:
            pairs = [{'group_id': i['group_id'], 'baseline': lookup[a, i['id']]['score'],
                      'candidate': lookup[b, i['id']]['score']} for i in eligible]
            wa, wb = (scores[s]['wer_lexical_corpus'] for s in (a, b))
            ci = paired_cluster_bootstrap(pairs, resamples=2000, seed=55, confidence=.95)
            comparisons[name] = {'baseline': a, 'candidate': b,
                'relative_reduction': (wa - wb)/wa if wa else None,
                'wer_delta': wb-wa if wa is not None and wb is not None else None,
                'bootstrap': ci, 'ci_interpretable_for_independent_sampling': ci['independent_groups'] > 1}
        value = {'inputs': len(selected), 'references': len(eligible), 'scores': scores, 'comparisons': comparisons}
        if cohort in {'noise_only', 'bleriot_b_noise'}:
            minutes = sum(i['duration_sec'] for i in selected)/60
            value.update(channel_minutes=minutes,
                inserted_words={s: sum(len(lexical_normalizer_v1(lookup[s, i['id']]['hypothesis']).split()) for i in selected) for s in MODELS})
            value['inserted_words_per_minute'] = {s: n/minutes for s, n in value['inserted_words'].items()}
        cohorts[cohort] = value
    result = {'status': 'EXECUTED_DIAGNOSTIC', 'cohorts': cohorts, 'records': len(rows),
        'runtime_failures': {s: sum(r['runtime_failure'] is not None for r in rows if r['system'] == s) for s in MODELS},
        'timing': {s: {'audio_sec': sum(r['duration_sec'] for r in rows if r['system'] == s),
                       'asr_sec': sum(r['asr_elapsed_sec'] for r in rows if r['system'] == s)} for s in MODELS},
        'plan_sha256': file_hash(EVAL / 'plan.json'), 'asr_quality_gate': 'NEEDS_MORE_DATA',
        'critical_entity_gate': 'NEEDS_MORE_DATA', 'nlp_quality_gate': 'NEEDS_MORE_DATA',
        'same_checkpoint_pipeline_gain_claimed': False, 'test_accessed': False, 'release_promoted': False,
        'limitations': plan['limitations']}
    atomic_json(EVAL / 'scored-rows.json', rows)
    atomic_json(EVAL / 'comparison.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'cohorts', 'limitations'}}, indent=2))


def cpu_smoke():
    import soundfile as sf

    from north55_speech.asr import AsrProvider
    from north55_speech.schemas import PipelineConfig

    plan = validate_eval()
    items = read(EVAL / 'inputs.json')
    provider = AsrProvider(PipelineConfig.model_validate(plan['configs']['augmented'] | {'device': 'cpu', 'compute_type': 'int8'}))
    rows = []
    for cohort in ('partial_human_dev', 'general_ru', 'bleriot_b_noise'):
        item = next(i for i in items if i['cohort'] == cohort)
        path = settings.audio_root / item['audio_path']
        if file_hash(path) != item['audio_sha256']:
            raise ValueError('CPU smoke audio changed')
        audio, rate = sf.read(path, dtype='float32')
        if rate != 16000 or audio.ndim != 1:
            raise ValueError('Invalid smoke audio')
        segments = provider.transcribe(audio, 0, item['input_language'], item['id'], lambda: None)
        rows.append({'id': item['id'], 'cohort': cohort,
                     'hypothesis': ' '.join(s.raw_asr_text.strip() for s in segments)})
    passed = provider.model.model.device == 'cpu' and all(r['hypothesis'] for r in rows[:2])
    result = {'status': 'PASS' if passed else 'FAIL', 'rows': rows,
        'actual_device': provider.model.model.device, 'actual_precision': provider.model.model.compute_type,
        'plan_sha256': file_hash(EVAL / 'plan.json'), 'purpose': 'offline_engineering_smoke_not_accuracy_gate'}
    atomic_json(Path('/smoke/cpu-smoke.json'), result)
    print(json.dumps(result, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('prepare', 'train', 'freeze-eval', 'infer', 'score', 'cpu'))
    p.add_argument('--arm', choices=ARMS)
    p.add_argument('--system', choices=tuple(MODELS))
    args = p.parse_args()
    if args.stage == 'train':
        if not args.arm:
            p.error('--arm required')
        train(args.arm)
    elif args.stage == 'infer':
        if not args.system:
            p.error('--system required')
        infer(args.system)
    else:
        {'prepare': prepare, 'freeze-eval': freeze_eval, 'score': score, 'cpu': cpu_smoke}[args.stage]()
