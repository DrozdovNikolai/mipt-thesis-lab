"""Bounded SOTERIA pseudo-label experiment; annotations and old models are read-only."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import random
import re
import shutil
import time
import unicodedata
from collections import Counter
from pathlib import Path

POLICY = {
    'seed': 55, 'updates': 160, 'accumulation': 4, 'learning_rate': 2e-5,
    'rank': 8, 'alpha': 16, 'dropout': .05, 'kl_weight': .5,
    'arms': ['replay_control', 'soteria_mix'], 'candidate': 'soteria_mix',
    'checkpoint_selection': 'fixed_final_only', 'encoder_frozen': True,
    'new_examples_per_update': 2, 'max_disagreement': .4,
    'min_length_ratio': .55, 'max_length_ratio': 1.8,
    'min_teacher_avg_logprob': -.8, 'min_teacher_word_probability': .65,
    'max_words_per_second': 5.5, 'max_repeated_trigram': 3,
    'numeric_check': 'reject conflicting explicit digit sequences when both ASRs use digits; spoken forms unresolved',
    'weak_targets': True, 'human_verified': False, 'test_accessed': False,
    'release_promoted': False,
}
ROOT = Path('/study')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def words(text):
    # This normalization is for admission only; official scoring uses frozen v12 metrics.
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", unicodedata.normalize('NFC', text).casefold())


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, token in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j-1] + (token != other)))
        previous = current
    return previous[-1]


def admission(row, large, small):
    reasons = []
    if row['split'] != 'train':
        raise ValueError('Dev/test must never enter admission')
    for prediction in (large, small):
        if prediction['sample_id'] != row['sample_id'] or prediction['audio_sha256'] != row['audio_sha256']:
            raise ValueError('Draft/audio identity mismatch')
        if prediction.get('human_verified') is not False or prediction.get('status') != 'machine':
            raise ValueError('Require explicit machine provenance')
    a, b = words(large['text']), words(small['text'])
    disagreement = distance(a, b) / max(len(a), len(b), 1)
    length_ratio = len(a) / max(len(b), 1)
    segments = large.get('segments', [])
    probs = [w['probability'] for s in segments for w in s.get('words', [])]
    mean_prob = sum(probs) / len(probs) if probs else 0.
    min_logprob = min((s['avg_logprob'] for s in segments), default=-999.)
    if large.get('error') or small.get('error') or not a or not b:
        reasons.append('missing_prediction')
    if not segments or any(s['language'] != 'en' for s in segments):
        reasons.append('teacher_language_not_en')
    if not 1 <= row['duration_sec'] <= 22:
        reasons.append('duration')
    if disagreement > POLICY['max_disagreement']:
        reasons.append('asr_disagreement')
    if not POLICY['min_length_ratio'] <= length_ratio <= POLICY['max_length_ratio']:
        reasons.append('length_mismatch')
    if mean_prob < POLICY['min_teacher_word_probability'] or min_logprob < POLICY['min_teacher_avg_logprob']:
        reasons.append('low_teacher_confidence')
    if len(a) / row['duration_sec'] > POLICY['max_words_per_second']:
        reasons.append('implausible_text_density')
    grams = Counter(tuple(a[i:i+3]) for i in range(len(a)-2))
    if max(grams.values(), default=0) >= POLICY['max_repeated_trigram']:
        reasons.append('repeated_trigram')
    digits = [re.findall(r'\d+(?:[.,]\d+)*', p['text']) for p in (large, small)]
    digits = [[v.replace(',', '') for v in seq] for seq in digits]
    if all(digits) and digits[0] != digits[1]:
        reasons.append('explicit_number_conflict')
    return {'id': row['sample_id'], 'accepted': not reasons, 'reasons': reasons,
            'disagreement': disagreement, 'length_ratio': length_ratio,
            'mean_word_probability': mean_prob, 'min_segment_logprob': min_logprob,
            'explicit_digits': digits, 'human_verified': False}


def schedules(old, new):
    rng = random.Random(POLICY['seed'])
    buckets = {'old': list(old), 'new': list(new)}
    pools = {'old': [], 'new': []}
    def take(key):
        if not pools[key]:
            pools[key] = buckets[key].copy()
            rng.shuffle(pools[key])
        return pools[key].pop()
    # The first two replay examples in each update are shared by both arms.
    common = [[take('old'), take('old')] for _ in range(POLICY['updates'])]
    control = [key for pair in common for key in pair + [take('old'), take('old')]]
    mixed = [key for pair in common for key in pair + [take('new'), take('new')]]
    return {'replay_control': control, 'soteria_mix': mixed}


def prepare(workspace):
    study = workspace / 'reports/soteria-training-v15'
    if study.exists():
        raise ValueError('Preserve existing experiment; use run stages to resume')
    study.mkdir(parents=True)
    save(study/'policy.json', POLICY)
    v14 = workspace/'reports/soteria-v14'
    packet = workspace/'data/curated/soteria-v14/packet'
    v12 = workspace/'reports/cockpit-reviewed-v12'
    legacy = workspace/'data/curated/cockpit-hard-v4/train.jsonl'
    train, dev = rows(packet/'train.jsonl'), rows(packet/'dev.jsonl')
    replay, references = rows(legacy), read(v12/'scoring/references.json')
    assert len(train) == 155 and len(dev) == 203 and len(replay) == 247 and len(references) == 16
    heldout = dev + references
    for field in ('sample_id', 'audio_sha256', 'recording_id', 'session_id', 'group_id'):
        assert not {r[field] for r in train + replay} & {r[field] for r in heldout}
    assert not {s for r in replay for s in r['speaker_ids']} & {s for r in references for s in r['speaker_ids']}
    verification = read(v14/'verification.json')
    prediction_hashes = verification.get('prediction_sha256', verification.get('prediction_hashes'))
    admitted, audit, bindings = [], [], {}
    for row in train:
        predictions = []
        hashes = {}
        for model in ('large', 'small'):
            path = v14/'predictions'/model/(row['sample_id']+'.json')
            value = read(path)
            assert value['plan_sha256'] == sha(v14/'experiment-plan.json')
            predictions.append(value)
            hashes[model] = sha(path)
            assert hashes[model] == prediction_hashes[str(path.relative_to(v14)).replace('/', '\\')]
            bindings[path.relative_to(workspace).as_posix()] = hashes[model]
        decision = admission(row, *predictions)
        audit.append(decision | {'duration_sec': row['duration_sec'], 'prediction_sha256': hashes})
        if decision['accepted']:
            admitted.append({'id': row['sample_id'], 'origin': 'soteria', 'audio_path': row['audio_path'],
                'audio_sha256': row['audio_sha256'], 'duration_sec': row['duration_sec'], 'channel': 0,
                'target': predictions[0]['text'], 'transcript_status': 'weak', 'human_verified': False,
                'scope': 'simulator_mixed_crew_ATC_instructor_unverified',
                'session_id': row['session_id'], 'recording_id': row['recording_id'],
                'source_manifest_automatic_training_eligible': False,
                'experimental_pseudo_training_eligible': True, 'prediction_sha256': hashes})
    if len(admitted) < 30:
        save(study/'admission.json', audit)
        raise ValueError('Too few accepted examples for this predefined experiment')
    for row in replay:
        assert row['split'] == 'train' and row['transcript_status'] == 'weak'
        assert row['annotation_provenance']['automatic_training_eligible'] is True
        admitted.append({'id': row['sample_id'], 'origin': 'replay', 'audio_path': row['audio_path'],
            'audio_sha256': row['audio_sha256'], 'duration_sec': row['duration_sec'], 'channel': row['channel'],
            'target': row['reference_text'], 'transcript_status': 'weak', 'human_verified': False,
            'session_id': row['session_id'], 'recording_id': row['recording_id']})
    assert len({r['id'] for r in admitted}) == len(admitted)
    save(study/'train.json', admitted)
    save(study/'admission.json', audit)
    save(study/'schedule.json', schedules([r['id'] for r in admitted if r['origin']=='replay'],
                                         [r['id'] for r in admitted if r['origin']=='soteria']))
    inputs = [dict(item, origin='human_cockpit', language='en') for item in read(v12/'inputs.json')]
    inputs += [{'id': r['sample_id'], 'file': r['audio_path'], 'origin': 'soteria_dev', 'language': 'auto',
                'audio_sha256': r['audio_sha256'], 'duration_sec': r['duration_sec']} for r in dev]
    save(study/'inputs.json', inputs)
    save(study/'scoring/references.json', references)
    shutil.copyfile(v12/'io/hybrid.json', study/'scoring/hybrid-v9.json')
    # Prediction baselines for SOTERIA are weak diagnostics, never human references.
    weak = {model: {r['sample_id']: read(v14/'predictions'/model/(r['sample_id']+'.json')) for r in dev}
            for model in ('small', 'large')}
    for model in weak:
        for row in dev:
            path = v14/'predictions'/model/(row['sample_id']+'.json')
            assert sha(path) == prediction_hashes[str(path.relative_to(v14)).replace('/', '\\')]
            assert weak[model][row['sample_id']]['audio_sha256'] == row['audio_sha256']
    save(study/'scoring/soteria-drafts.json', weak)
    source_paths = [packet/'train.jsonl', packet/'dev.jsonl', legacy, v12/'plan.json', v12/'inputs.json',
                    v12/'scoring/references.json', v12/'io/hybrid.json', v14/'experiment-plan.json',
                    v14/'verification.json', v14/'model-small.json', v14/'model-large.json']
    bindings.update({p.relative_to(workspace).as_posix(): sha(p) for p in source_paths})
    frozen = study/'frozen'
    shutil.copytree(v14/'frozen/src', frozen/'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('scripts/soteria_training_v15.py', 'scripts/run_soteria_training_v15.py', 'tests/test_soteria_training_v15.py'):
        target = frozen/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workspace/name, target)
    code = {p.relative_to(frozen).as_posix(): sha(p) for p in frozen.rglob('*') if p.is_file()}
    input_hashes = {name: sha(study/name) for name in ('policy.json', 'train.json', 'admission.json', 'schedule.json', 'inputs.json',
                    'scoring/references.json', 'scoring/hybrid-v9.json', 'scoring/soteria-drafts.json')}
    old_plan = read(workspace/'reports/cockpit-training-v4/plan.json')
    plan = {'policy': POLICY, 'inputs': input_hashes, 'code': code, 'sources': bindings,
            'base_manifest': old_plan['base_manifest'], 'baseline_config': read(v12/'plan.json')['baseline_config'],
            'soteria_config': read(v14/'model-small.json')['config'],
            'strict_ids': read(v12/'plan.json')['strict_ids'],
            'v14_models': {m: read(v14/f'model-{m}.json')['manifest'] for m in ('small', 'large')},
            'train_counts': dict(Counter(r['origin'] for r in admitted)),
            'train_minutes': {origin: sum(r['duration_sec'] for r in admitted if r['origin']==origin)/60 for origin in ('replay','soteria')},
            'eval_counts': {'human_cockpit': 16, 'soteria_dev': 203},
            'rejections': dict(Counter(reason for a in audit for reason in a['reasons'])),
            'bleriot_speakers_disjoint': True, 'source_sessions_disjoint': True,
            'soteria_shared_actors_unresolved': True, 'new_human_annotations': 0,
            'test_accessed': False, 'release_promoted': False}
    save(study/'plan.json', plan)
    print(json.dumps({k: plan[k] for k in ('train_counts','train_minutes','rejections')}, indent=2), flush=True)


def validate(names=()):
    plan = read(ROOT/'plan.json')
    assert plan['policy'] == POLICY
    for name, expected in plan['code'].items():
        assert sha(Path('/app')/name) == expected, name
    for name in names:
        assert sha(ROOT/name) == plan['inputs'][name], name
    return plan


def verify_files(folder, manifest):
    for name, expected in manifest['files'].items():
        path = (folder/name).resolve()
        assert path.is_relative_to(folder.resolve()) and sha(path) == expected, name


def load_wave(row):
    import numpy as np
    import soundfile as sf
    roots = {'soteria': Path('/soteria'), 'replay': Path('/legacy'),
             'human_cockpit': Path('/human'), 'soteria_dev': Path('/soteria')}
    root = roots[row['origin']]
    path = (root/row.get('audio_path', row.get('file'))).resolve()
    assert path.is_relative_to(root) and sha(path) == row['audio_sha256']
    wave, rate = sf.read(path, dtype='float32', always_2d=True)
    channel = row.get('channel', 0)
    assert rate == 16000 and channel < wave.shape[1]
    wave = wave[:, channel].copy()
    assert 0 < len(wave) <= 480000 and np.isfinite(wave).all()
    assert abs(len(wave)/rate-row['duration_sec']) < .002
    return wave


def train():
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, set_seed
    from transformers.modeling_outputs import BaseModelOutput
    from north55_speech.decoder_adaptation import decoder_targets, tensor_hashes, verify_trainable_decoder
    from north55_speech.retention import base_teacher_logits, masked_teacher_kl

    plan = validate(('train.json', 'schedule.json'))
    samples, schedule = read(ROOT/'train.json'), read(ROOT/'schedule.json')
    assert torch.cuda.device_count() == 1 and torch.cuda.is_bf16_supported()
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    base = Path('/models/whisper-small-transformers')
    verify_files(base, plan['base_manifest'])
    set_seed(POLICY['seed'])
    processor = WhisperProcessor.from_pretrained(base, local_files_only=True)
    processor.tokenizer.set_prefix_tokens(language='en', task='transcribe')
    original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True).cuda().eval()
    before, encoder_before = tensor_hashes(original), tensor_hashes(original.model.encoder)
    cache, contracts = {}, []
    started = time.perf_counter()
    for row in samples:
        wave = load_wave(row)
        tokens = processor.tokenizer(row['target']).input_ids
        assert row['human_verified'] is False and row['transcript_status'] == 'weak'
        assert 4 < len(tokens) <= 448 and tokens[0] == original.config.decoder_start_token_id
        features = processor.feature_extractor(wave, sampling_rate=16000, return_tensors='pt').input_features.cuda()
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
            states = original.model.encoder(features).last_hidden_state.cpu()
        labels = torch.tensor([tokens[1:]], dtype=torch.long)
        cache[row['id']] = (states, labels)
        contracts.append({'id': row['id'], 'audio_sha256': row['audio_sha256'], 'samples': len(wave),
            'pcm_sha256': hashlib.sha256(wave.astype('<f4').tobytes()).hexdigest(),
            'target_sha256': hashlib.sha256(row['target'].encode()).hexdigest(), 'tokens': len(tokens)})
        if len(cache) % 50 == 0:
            print('Encoded training audio', len(cache), '/', len(samples), flush=True)
    save(ROOT/'audio-contracts.json', contracts)
    del original, features, states
    gc.collect()
    torch.cuda.empty_cache()
    initial_hashes = []
    outcomes = {}
    for arm in POLICY['arms']:
        folder = ROOT/'models'/arm/'adapter'
        assert not folder.exists(), 'Never overwrite a training arm'
        set_seed(POLICY['seed'])
        original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        original.config.use_cache = False
        model = get_peft_model(original, LoraConfig(r=POLICY['rank'], lora_alpha=POLICY['alpha'],
            target_modules=decoder_targets(original), lora_dropout=POLICY['dropout'], bias='none')).cuda()
        trainable = verify_trainable_decoder(model)
        params = [p for p in model.parameters() if p.requires_grad]
        initial_hash = hashlib.sha256(b''.join(p.detach().cpu().numpy().tobytes() for p in params)).hexdigest()
        initial_hashes.append(initial_hash)
        optimizer = torch.optim.AdamW(params, lr=POLICY['learning_rate'], weight_decay=0., fused=True)
        model.train()
        seen, logs, ce_sum, kl_sum = Counter(), [], 0., 0.
        arm_started = time.perf_counter()
        for update in range(POLICY['updates']):
            optimizer.zero_grad(set_to_none=True)
            for key in schedule[arm][update*4:update*4+4]:
                states, target = cache[key]
                batch = {'encoder_outputs': BaseModelOutput(last_hidden_state=states.cuda()), 'labels': target.cuda()}
                with torch.autocast('cuda', dtype=torch.bfloat16):
                    teacher = base_teacher_logits(model, **batch)
                    output = model(**batch)
                    kl = masked_teacher_kl(output.logits, teacher, batch['labels'])
                    loss = output.loss + POLICY['kl_weight']*kl
                assert torch.isfinite(loss)
                (loss/4).backward()
                ce_sum += float(output.loss.detach())
                kl_sum += float(kl.detach())
                seen[key] += 1
                del teacher, output, kl, loss
            grad = torch.nn.utils.clip_grad_norm_(params, 1., error_if_nonfinite=True)
            optimizer.step()
            if (update+1) % 20 == 0:
                entry = {'update': update+1, 'ce': ce_sum/80, 'kl': kl_sum/80,
                         'gradient_norm': float(grad), 'seconds': time.perf_counter()-arm_started}
                logs.append(entry)
                print(arm, json.dumps(entry), flush=True)
                ce_sum = kl_sum = 0.
        assert {int(v['step']) for v in optimizer.state.values()} == {POLICY['updates']}
        assert len(optimizer.state) == len(trainable) == 96
        assert set(seen) == set(schedule[arm])
        verify_trainable_decoder(model)
        assert tensor_hashes(model.get_base_model().model.encoder) == encoder_before
        after = {n.replace('.base_layer.', '.'): hashlib.sha256(p.detach().cpu().contiguous().numpy().tobytes()).hexdigest()
                 for n, p in model.get_base_model().state_dict().items() if '.lora_' not in n}
        assert before == after
        model.save_pretrained(folder, safe_serialization=True)
        torch.save(optimizer.state_dict(), folder/'optimizer.pt')
        outcomes[arm] = {'actual_updates': POLICY['updates'], 'optimizer_tensors': len(optimizer.state),
            'initial_adapter_sha256': initial_hash, 'coverage': dict(seen), 'history': logs,
            'seconds': time.perf_counter()-arm_started, 'frozen_base_unchanged': True, 'encoder_unchanged': True,
            'files': {p.name: sha(p) for p in folder.iterdir() if p.is_file()}}
        save(ROOT/f'training-{arm}.json', outcomes[arm])
        del model, original, optimizer, params, batch
        gc.collect()
        torch.cuda.empty_cache()
    assert len(set(initial_hashes)) == 1
    save(ROOT/'training.json', {'plan_sha256': sha(ROOT/'plan.json'), 'arms': outcomes,
         'seconds': time.perf_counter()-started, 'GPU': torch.cuda.get_device_name(0),
         'dev_used_for_training': False, 'human_targets_used': False, 'test_accessed': False})


def convert():
    import torch
    from peft import PeftModel
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, WhisperTokenizerFast
    from ctranslate2.converters import TransformersConverter
    plan = validate()
    training = read(ROOT/'training.json')
    assert training['plan_sha256'] == sha(ROOT/'plan.json')
    base = Path('/models/whisper-small-transformers')
    verify_files(base, plan['base_manifest'])
    torch.set_num_threads(4)
    for arm in POLICY['arms']:
        folder = ROOT/'models'/arm
        verify_files(folder/'adapter', training['arms'][arm])
        assert not (folder/'merged').exists() and not (folder/'ct2').exists()
        model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        adapted = PeftModel.from_pretrained(model, folder/'adapter', local_files_only=True)
        merged = adapted.merge_and_unload()
        merged.save_pretrained(folder/'merged', safe_serialization=True)
        WhisperProcessor.from_pretrained(base, local_files_only=True).save_pretrained(folder/'merged')
        WhisperTokenizerFast.from_pretrained(base, local_files_only=True).save_pretrained(folder/'merged')
        del merged, adapted, model
        gc.collect()
        TransformersConverter(str(folder/'merged'), copy_files=['tokenizer.json','preprocessor_config.json']).convert(str(folder/'ct2'), quantization='float16')
        manifest = {'model': arm, 'files': {p.name: sha(p) for p in (folder/'ct2').iterdir() if p.is_file()},
                    'plan_sha256': sha(ROOT/'plan.json'), 'adapter_sha256': sha(folder/'adapter/adapter_model.safetensors'),
                    'training': POLICY, 'release_allowed': False,
                    'license': 'inherits model and CC-BY-NC-4.0 replay data restrictions; noncommercial research'}
        save(folder/'ct2/manifest.json', manifest)
        print('Converted', arm, flush=True)


def infer(arm):
    from faster_whisper import WhisperModel
    from north55_speech.asr import AsrProvider
    from north55_speech.schemas import PipelineConfig
    plan = validate(('inputs.json',))
    if arm in POLICY['arms']:
        folder = ROOT/'models'/arm/'ct2'
        manifest = read(folder/'manifest.json')
    else:
        manifest = plan['v14_models'][arm]
        folder = Path('/models')/manifest['model']
    verify_files(folder, manifest)
    model = WhisperModel(str(folder), device='cuda', compute_type='float16', local_files_only=True, cpu_threads=4)
    inputs = read(ROOT/'inputs.json')
    if arm in ('small','large'):
        inputs = [r for r in inputs if r['origin']=='human_cockpit']
    output = ROOT/'predictions'/arm
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    config_records = {}
    for index, row in enumerate(inputs):
        destination = output/(row['id']+'.json')
        config = PipelineConfig.model_validate(plan['baseline_config'] if row['origin']=='human_cockpit' else plan['soteria_config'])
        provider = object.__new__(AsrProvider)
        provider.config = config
        provider.model = model
        options = provider.options(row['language'])
        config_records[row['origin']] = options
        identity = {'id': row['id'], 'audio_sha256': row['audio_sha256'], 'plan_sha256': sha(ROOT/'plan.json'),
                    'model_manifest_sha256': sha(folder/'manifest.json'), 'options': options}
        if destination.exists():
            cached = read(destination)
            assert all(cached[k] == v for k,v in identity.items())
            continue
        wave = load_wave(row)
        call_started = time.perf_counter()
        segments, info = model.transcribe(wave, **options)
        segments = list(segments)
        save(destination, identity | {'hypothesis': ' '.join(s.text.strip() for s in segments),
            'language': info.language, 'seconds': time.perf_counter()-call_started,
            'segments': [{'start': s.start, 'end': s.end, 'text': s.text, 'avg_logprob': s.avg_logprob} for s in segments],
            'error': None})
        if (index+1) % 25 == 0 or index+1 == len(inputs):
            print(arm, index+1, '/', len(inputs), flush=True)
    save(ROOT/f'inference-{arm}.json', {'items': len(inputs), 'seconds': time.perf_counter()-started,
        'model_manifest': manifest, 'options_by_cohort': config_records, 'plan_sha256': sha(ROOT/'plan.json')})


def score():
    from north55_speech.metrics import edit_counts, lexical_normalizer_v1, canonical_normalizer_v1
    plan = validate(('inputs.json','scoring/references.json','scoring/hybrid-v9.json','scoring/soteria-drafts.json'))
    refs = read(ROOT/'scoring/references.json')
    inputs = {r['id']: r for r in read(ROOT/'inputs.json')}
    predictions = {}
    hashes = {}
    for arm in POLICY['arms'] + ['small','large']:
        predictions[arm] = {}
        execution = read(ROOT/f'inference-{arm}.json')
        assert execution['plan_sha256'] == sha(ROOT/'plan.json')
        for path in sorted((ROOT/'predictions'/arm).glob('*.json')):
            row = read(path)
            assert row['audio_sha256'] == inputs[row['id']]['audio_sha256'] and row['error'] is None
            assert row['plan_sha256'] == sha(ROOT/'plan.json')
            model_folder = ROOT/'models'/arm/'ct2' if arm in POLICY['arms'] else Path('/models')/plan['v14_models'][arm]['model']
            assert row['model_manifest_sha256'] == sha(model_folder/'manifest.json')
            assert row['options'] == execution['options_by_cohort'][inputs[row['id']]['origin']]
            predictions[arm][row['id']] = row['hypothesis']
            hashes[path.relative_to(ROOT).as_posix()] = sha(path)
        expected = set(inputs) if arm in POLICY['arms'] else {r['sample_id'] for r in refs}
        assert set(predictions[arm]) == expected
    hybrid = read(ROOT/'scoring/hybrid-v9.json')
    predictions['previous_v9'] = {}
    for r in hybrid['records']:
        key = Path(r['input_path']).stem
        assert r['input_sha256'] == inputs[key]['audio_sha256']
        predictions['previous_v9'][key] = r['hypothesis']
    per_clip = []
    for ref in refs:
        key = ref['sample_id']
        item = {'id': key, 'strict': key in plan['strict_ids'], 'reference': ref['reference_text'], 'models': {}}
        for arm, pred in predictions.items():
            counts = edit_counts(ref['reference_text'], pred[key])
            assert sum(counts[k] for k in ('S','D','I')) == distance(words_for_score(ref['reference_text']), words_for_score(pred[key]))
            canonical = edit_counts(canonical_normalizer_v1(ref['reference_text']), canonical_normalizer_v1(pred[key]))
            item['models'][arm] = {'hypothesis': pred[key], 'lexical': counts, 'canonical': canonical}
        per_clip.append(item)
    summaries = {}
    for cohort in ('all_16','strict_10'):
        selected = [r for r in per_clip if cohort=='all_16' or r['strict']]
        summaries[cohort] = {}
        for arm in predictions:
            summaries[cohort][arm] = {}
            for metric in ('lexical','canonical'):
                counts = {k: sum(r['models'][arm][metric][k] for r in selected) for k in ('S','D','I','N')}
                errors = sum(counts[k] for k in ('S','D','I'))
                summaries[cohort][arm][metric] = counts | {'errors': errors, 'wer': errors/counts['N']}
    weak = read(ROOT/'scoring/soteria-drafts.json')
    diagnostics = {}
    for arm in ['small'] + POLICY['arms']:
        total, count = 0, 0
        for key, reference in weak['large'].items():
            assert reference['audio_sha256'] == inputs[key]['audio_sha256']
            hypothesis = weak['small'][key]['text'] if arm=='small' else predictions[arm][key]
            a, b = words_for_score(reference['text']), words_for_score(hypothesis)
            total += distance(a,b)
            count += len(a)
        diagnostics[arm] = {'edit_distance_to_machine_teacher': total, 'teacher_words': count,
                            'distance_per_teacher_word': total/count, 'is_human_WER': False, 'clips': len(weak['large'])}
    result = {'status': 'COMPLETED_DIAGNOSTIC', 'plan_sha256': sha(ROOT/'plan.json'),
              'training': read(ROOT/'training.json'), 'human_cockpit': summaries, 'soteria_weak_diagnostics': diagnostics,
              'per_clip': per_clip, 'new_ASR_calls': len(hashes), 'new_human_annotations': 0,
              'test_accessed': False, 'release_promoted': False,
              'limitations': ['16 user-selected machine-assisted human references, three BLeRIOT speakers',
                'SOTERIA evaluation uses machine labels only; teacher agreement is not recognition accuracy',
                'SOTERIA source crews disjoint but shared ATC/instructor identities unresolved',
                'Same-family Whisper teachers can share errors; spoken number conflicts not fully detectable',
                'No hyperparameter search; both final checkpoints fixed before inference']}
    save(ROOT/'comparison.json', result)
    save(ROOT/'verification.json', {'status': 'PASS', 'prediction_sha256': hashes,
         'scored_human_pairs': len(refs)*len(predictions), 'independent_edit_distance_checks': len(refs)*len(predictions),
         'actual_optimizer_updates': {arm: result['training']['arms'][arm]['actual_updates'] for arm in POLICY['arms']},
         'source_annotations_modified_by_experiment': False, 'test_accessed': False})
    text = '# SOTERIA: обучение на машинных расшифровках\n\n'
    text += f"Новые слабые данные: {plan['train_counts']['soteria']} фрагментов, {plan['train_minutes']['soteria']:.2f} минуты. "
    text += f"Повтор прежних кабинных данных: 247 фрагментов, {plan['train_minutes']['replay']:.2f} минуты.\n\n"
    text += 'Два обучения с одинаковой инициализацией: контроль только на прежних данных и смесь 50/50 с SOTERIA. '
    text += 'По 160 обновлений AdamW, четыре примера на обновление, LoRA декодера и KL к исходной модели. Выбраны заранее последние состояния.\n\n'
    text += '| Система | WER: все 16 | WER: строгие 10 |\n|---|---:|---:|\n'
    labels = {'small':'Исходный Whisper small (согласованная конверсия)', 'replay_control':'Контроль: прежние данные',
              'soteria_mix':'Новый кандидат: прежние данные + SOTERIA', 'large':'Whisper large-v3 без обучения', 'previous_v9':'Прежний профиль v9 (сохранённые ответы)'}
    for arm in ['small','replay_control','soteria_mix','large','previous_v9']:
        text += '| '+labels[arm]+' | '+' | '.join(f"{summaries[c][arm]['lexical']['wer']:.2%} ({summaries[c][arm]['lexical']['errors']}/{summaries[c][arm]['lexical']['N']})" for c in summaries)+' |\n'
    text += '\nЭто диагностические 16 пользовательских расшифровок, 203 слова, 160 секунд; не независимая приёмка. '
    text += 'Строгая подвыборка — 10 записей с подтверждением текста, языка и области. Все тексты сохранены без исправлений.\n\n'
    text += '203 фрагмента SOTERIA остались вне обучения и распознаны обеими новыми моделями. '
    text += 'Сравнение с large-v3 хранится как расстояние до машинного текста, а не как человеческий WER.\n\n'
    text += f"Выполнено {len(hashes)} новых распознаваний; проверены все идентификаторы, хеши аудио и оба состояния оптимизатора. "
    text += 'Test и рабочий сервис не изменены. Ручная разметка не создавалась.\n\n'
    text += 'Модели и адаптеры: `models/{replay_control,soteria_mix}/`; подробности: `comparison.json`, `admission.json`, `verification.json`.\n'
    (ROOT/'report.md').write_text(text, encoding='utf-8')
    print(json.dumps(summaries, indent=2), flush=True)


def words_for_score(text):
    from north55_speech.metrics import lexical_normalizer_v1
    return lexical_normalizer_v1(text).split()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare','train','convert','infer','score'])
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--arm', choices=POLICY['arms']+['small','large'])
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare(args.workspace)
    elif args.stage == 'infer':
        assert args.arm
        infer(args.arm)
    else:
        globals()[args.stage]()
