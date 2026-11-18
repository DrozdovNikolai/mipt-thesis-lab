"""Matched v7 training: old weak data versus additional cross-family labels."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.core import file_hash
from north55_speech.cross_data_adaptation import (
    ARMS,
    TRAINING,
    balanced_schedule,
    expand_without_overlaps,
)
from scripts import nus_convergence as worker
from scripts.decoding_diagnostics import load_audio as original_audio_loader

ROOT, EXP = Path('/study'), Path('/experiment')
read, save = worker.read, worker.save_new


def pcm(x):
    return hashlib.sha256(x.astype('<f4').tobytes()).hexdigest()


def validate():
    plan = worker.validate()
    if plan['training'] != TRAINING:
        raise ValueError('Frozen training recipe changed')
    return plan


def prepare():
    from north55_speech.datasets import load_manifest, validate_groups, write_manifest
    from north55_speech.hard_adaptation import validate_population
    from north55_speech.training import check_training_partitions
    from scripts.cockpit_cross_asr_rules_v6 import interval_union_seconds

    if (ROOT/'plan.json').exists() or (ROOT/'frozen').exists():
        raise ValueError('Preserve completed preparation')
    EXP.mkdir(exist_ok=True)
    os.chown(EXP, 10001, 10001)
    prior, cross = Path('/app/reports/cockpit-robust-v5'), Path('/app/reports/cockpit-cross-asr-v6')
    old_plan = read(prior/'plan.json')
    assert read(cross/'verification.json')['status'] == 'PASS'
    completion = read(cross/'completion.json')
    for name in ('datasets/supplemental-weak-train.jsonl', 'comparison.json', 'verification.json'):
        assert file_hash(cross/name) == completion['artifact_sha256'][name]
    data = Path('/app/data/curated/cockpit-hard-v4')
    old, dev = (load_manifest(data/(s+'.jsonl')) for s in ('train', 'dev'))
    assert file_hash(data/'train.jsonl') == old_plan['train_sha256']
    assert file_hash(data/'dev.jsonl') == old_plan['dev_sha256']
    validate_population(old, dev)
    supplemental = load_manifest(cross/'datasets/supplemental-weak-train.jsonl')
    for row in supplemental:
        p = row.annotation_provenance
        assert row.split == 'train' and row.transcript_status == 'weak' and not row.primary
        assert not row.scope_verified and not p['human_verified'] and not p['reviewed_audio']
        assert p['method'] == 'cross_family_consensus_v6' and p['automatic_training_eligible']
        assert p['target_origin'] == 'unprompted_parakeet_tdt_v2' and p['supporting_teachers']
        assert p['publisher_support']['coverage'] >= .9 and p['publisher_support']['critical_supported']
        assert p['selection_plan_sha256'] == file_hash(cross/'inference/plan.json')
    expanded, removed = expand_without_overlaps(old, supplemental)
    assert (len(old), len(supplemental), len(removed), len(expanded)) == (247, 18, 6, 259)
    check_training_partitions(expanded, dev)
    validate_groups([s.model_copy(deep=True, update={'group_id': None}) for s in expanded+dev])
    datasets = ROOT/'datasets'
    datasets.mkdir(exist_ok=True)
    write_manifest(datasets/'control.jsonl', old)
    write_manifest(datasets/'expanded.jsonl', expanded)
    write_manifest(datasets/'union.jsonl', old+supplemental)
    # No dev labels are mounted in the trainer; partition checks finish here.
    schedules = {a: balanced_schedule(rows) for a, rows in [('control', old), ('expanded', expanded)]}
    assert schedules['control'] == read(prior/'schedule.json')['balanced']
    assert [(e['seed'], e['augmented']) for e in schedules['control']] == [(e['seed'], e['augmented']) for e in schedules['expanded']]
    save(ROOT/'schedule.json', schedules)
    intervals = {}
    for s in expanded:
        if not s.variant_of:
            p = s.annotation_provenance
            intervals.setdefault(p['source_sample_id'], []).append((p['original_start_sec'], p['original_end_sec']))
    unique_seconds = sum(interval_union_seconds(v) for v in intervals.values())
    audit = {'control_rows': 247, 'expanded_rows': 259, 'new_weak_rows': 18, 'replacements': removed,
        'expanded_seconds': sum(s.duration_sec for s in expanded), 'clean_unique_seconds': unique_seconds,
        'overlapping_clean_intervals': 0, 'partition_check': 'PASS', 'human_verified': False}
    save(ROOT/'data-audit.json', audit)
    for name, key in [('inputs.json', 'inputs_sha256'), ('scoring/references.json', 'references_sha256')]:
        assert file_hash(prior/name) == old_plan[key]
    inputs, refs = read(prior/'inputs.json'), read(prior/'scoring/references.json')
    gates = read(prior/'io-vad/vad.json')
    assert gates['plan_sha256'] == file_hash(prior/'plan.json')
    history = {}
    for system in ('baseline', 'balanced'):
        execution = read(prior/('io-'+system)/'execution.json')
        assert not execution['runtime_failures'] and execution['records'] == 541
        rows = {}
        for item in inputs:
            path = prior/('io-'+system)/'predictions'/(item['id']+'.json')
            assert file_hash(path) == execution['prediction_sha256'][path.name]
            rows[item['id']] = read(path)
        history[system] = rows
    for sample in supplemental:
        identity = 'new-fit-'+sample.sample_id
        inputs.append({'id': identity, 'reference_id': identity, 'cohort': 'train_new_fit',
            'audio_path': sample.audio_path, 'audio_sha256': sample.audio_sha256,
            'duration_sec': sample.duration_sec, 'channel': 0, 'input_language': 'en', 'gain_db': 0.,
            'group_id': sample.group_id})
        refs[identity] = sample.reference_text
    assert len(inputs) == len({i['id'] for i in inputs}) == 559
    directory = EXP/'eval-audio'
    directory.mkdir(exist_ok=True)
    for item in inputs:
        if item.get('synthetic_v5'):
            source = Path('/robust/eval-audio')/(item['id']+'.wav')
            assert file_hash(source) == item['audio_sha256']
            shutil.copyfile(source, directory/source.name)
    save(ROOT/'inputs.json', inputs)
    save(ROOT/'scoring/references.json', refs)
    save(ROOT/'scoring/history.json', history)
    save(ROOT/'scoring/vad.json', gates)
    frozen = ROOT/'frozen'
    for name in ('src', 'scripts', 'tests', 'configs'):
        shutil.copytree(Path('/app')/name, frozen/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('pyproject.toml', 'uv.lock', 'SPEC.md', 'ACCEPTANCE.yaml'):
        shutil.copyfile(Path('/app')/name, frozen/name)
    code = {p.relative_to(frozen).as_posix(): file_hash(p) for p in sorted(frozen.rglob('*')) if p.is_file()}
    plan = {'training': TRAINING, 'implementation_sha256': code,
        'protocol_sha256': file_hash(ROOT/'protocol.md'), 'inputs_sha256': file_hash(ROOT/'inputs.json'),
        'references_sha256': file_hash(ROOT/'scoring/references.json'), 'schedule_sha256': file_hash(ROOT/'schedule.json'),
        'dataset_sha256': {p.name: file_hash(p) for p in datasets.iterdir()},
        'selected_ids': {a: [s.sample_id for s in rows] for a, rows in [('control', old), ('expanded', expanded)]},
        'base_manifest': old_plan['base_manifest'], 'baseline_model': old_plan['baseline_model'], 'config': old_plan['config'],
        'train_sha256': file_hash(datasets/'expanded.jsonl'), 'prior_plan_sha256': file_hash(prior/'plan.json'),
        'history_sha256': file_hash(ROOT/'scoring/history.json'), 'vad_sha256': file_hash(ROOT/'scoring/vad.json'),
        'model_names': {a: 'whisper-small-cockpit-data-v7-'+a for a in ARMS},
        'quality_evidence': False, 'selection_allowed': False, 'release_promoted': False,
        'test_accessed': False, 'blind_dev_accessed': False,
        'budget': {'training_runs': 2, 'updates_each': 240, 'new_GPU_ASR': 1136, 'CPU_ASR': 4}}
    save(ROOT/'plan.json', plan)
    print(json.dumps(audit | {'budget': plan['budget']}), flush=True)


def train():
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, set_seed
    from transformers.modeling_outputs import BaseModelOutput

    from north55_speech.datasets import load_manifest
    from north55_speech.decoder_adaptation import tensor_hashes, verify_trainable_decoder
    from north55_speech.hard_adaptation import targets
    from north55_speech.robust_adaptation import augment_waveform, mask_features

    plan = validate()
    assert file_hash(ROOT/'schedule.json') == plan['schedule_sha256']
    for name, digest in plan['dataset_sha256'].items():
        assert file_hash(Path('/train')/name) == digest
    schedules = read(ROOT/'schedule.json')
    for arm in ARMS:
        assert [s.sample_id for s in load_manifest(Path('/train')/(arm+'.jsonl'))] == plan['selected_ids'][arm]
    samples = load_manifest(Path('/train/union.jsonl'))
    assert len(samples) == 265 and all(s.split == 'train' for s in samples)
    assert torch.cuda.is_available() and torch.cuda.device_count() == 1 and torch.cuda.is_bf16_supported()
    base, destination = Path('/models/whisper-small-transformers'), EXP/'training'
    worker.verify_files(base, plan['base_manifest']['files'])
    if destination.exists():
        raise ValueError('Preserve previous training')
    destination.mkdir()
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    set_seed(55)
    processor = WhisperProcessor.from_pretrained(base, local_files_only=True)
    processor.tokenizer.set_prefix_tokens(language='en', task='transcribe')
    original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True).cuda().eval()
    encoder_before, base_before = tensor_hashes(original.model.encoder), tensor_hashes(original)
    waves, labels, cache, contracts, keys = {}, {}, {}, [], {}
    for sample in samples:
        path = (Path('/audio')/sample.audio_path).resolve()
        assert path.is_relative_to(Path('/audio')) and file_hash(path) == sample.audio_sha256
        x, rate = sf.read(path, dtype='float32')
        assert rate == 16000 and x.ndim == 1 and np.isfinite(x).all() and 0 < len(x) <= 480000
        assert abs(len(x)/16000-sample.duration_sec) <= 1/16000
        tokens = processor.tokenizer(sample.reference_text).input_ids
        assert sample.reference_text and tokens[0] == original.config.decoder_start_token_id and len(tokens) <= 448
        waves[sample.sample_id] = x
        labels[sample.sample_id] = torch.tensor([tokens[1:]], dtype=torch.long)

    def encode(key, parent, seed=None, wave_cache=waves, label_cache=labels, encoder_model=original):
        if key in cache:
            return
        x, target = wave_cache[parent], label_cache[parent]
        meta = {'parent': parent, 'augmented': seed is not None, 'seed': seed}
        if seed is not None:
            x, details = augment_waveform(x, seed)
            meta['augmentation'] = details
        features = processor.feature_extractor(x, sampling_rate=16000, return_tensors='pt').input_features
        if seed is not None:
            features, meta['specaugment'] = mask_features(features, len(x), seed+23)
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
            states = encoder_model.model.encoder(features.cuda()).last_hidden_state.cpu()
        cache[key] = (states, target)
        contracts.append({'key': key, 'audio_samples': len(x), 'waveform_sha256': pcm(x),
            'encoder_state_sha256': hashlib.sha256(states.view(torch.uint8).numpy().tobytes()).hexdigest(),
            'label_sha256': hashlib.sha256(target.numpy().tobytes()).hexdigest(), 'metadata': meta})
        if len(contracts) % 100 == 0:
            print('Cached', len(contracts), flush=True)

    started = time.perf_counter()
    for parent in waves:
        encode(parent, parent)
    for arm, schedule in schedules.items():
        keys[arm] = []
        for entry in schedule:
            parent = entry['parent']
            key = parent if not entry['augmented'] else parent+'@'+str(entry['seed'])
            encode(key, parent, entry['seed'] if entry['augmented'] else None)
            keys[arm].append(key)
    save(Path('/output/audio-contracts.json'), contracts)
    cache_seconds = time.perf_counter()-started
    del encode, original, waves, labels, x
    gc.collect()
    torch.cuda.empty_cache()
    set_seed(55)
    initial_base = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
    initial_model = get_peft_model(initial_base, LoraConfig(r=8, lora_alpha=16,
        target_modules=targets(initial_base, True), lora_dropout=.05, bias='none'))
    shared = {n: p.detach().clone() for n, p in initial_model.named_parameters() if p.requires_grad and '.decoder.' in n}
    del initial_model, initial_base
    gc.collect()
    arms, checkpoints = {}, {}
    for arm in ARMS:
        set_seed(55)
        base_model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        base_model.config.use_cache = False
        model = get_peft_model(base_model, LoraConfig(r=8, lora_alpha=16,
            target_modules=targets(base_model, False), lora_dropout=.05, bias='none')).cuda()
        verify_trainable_decoder(model)
        with torch.no_grad():
            for name, p in model.named_parameters():
                if p.requires_grad:
                    p.copy_(shared[name].to(p.device))
        initial_hash = hashlib.sha256(b''.join(p.detach().cpu().numpy().tobytes() for p in model.parameters() if p.requires_grad)).hexdigest()
        set_seed(55)
        params = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(params, lr=2e-5, weight_decay=0., fused=True)
        optimizer.zero_grad(set_to_none=True)
        seen, logs, total = Counter(), [], 0.
        model.train()
        started = time.perf_counter()
        for update in range(240):
            for key in keys[arm][4*update:4*update+4]:
                states, target = cache[key]
                with torch.autocast('cuda', dtype=torch.bfloat16):
                    loss = model(encoder_outputs=BaseModelOutput(last_hidden_state=states.cuda()), labels=target.cuda()).loss
                assert torch.isfinite(loss)
                (loss/4).backward()
                total += float(loss.detach())
                seen[key] += 1
            grad = torch.nn.utils.clip_grad_norm_(params, 1., error_if_nonfinite=True)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            if (update+1) % 20 == 0:
                record = {'updates': update+1, 'speech_ce': total/80, 'gradient_norm': float(grad), 'seconds': time.perf_counter()-started}
                logs.append(record)
                print(arm, json.dumps(record), flush=True)
                total = 0.
        assert {int(s['step']) for s in optimizer.state.values()} == {240} and len(optimizer.state) == 96
        assert {k.split('@')[0] for k in seen} == set(plan['selected_ids'][arm])
        verify_trainable_decoder(model)
        assert tensor_hashes(model.get_base_model().model.encoder) == encoder_before
        after = {n.replace('.base_layer.', '.'): hashlib.sha256(p.detach().cpu().contiguous().numpy().tobytes()).hexdigest()
            for n, p in model.get_base_model().state_dict().items() if '.lora_' not in n}
        assert after == base_before
        folder = destination/('checkpoint-'+arm)
        model.save_pretrained(folder, safe_serialization=True)
        torch.save(optimizer.state_dict(), folder/'optimizer.pt')
        torch.save({'cpu': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state()}, folder/'rng.pt')
        checkpoints[arm] = {p.name: file_hash(p) for p in folder.iterdir() if p.is_file()}
        arms[arm] = {'actual_updates': 240, 'optimizer_tensors': 96, 'initial_adapter_sha256': initial_hash,
            'coverage': dict(seen), 'history': logs, 'speech_presentations': 960,
            'encoder_unchanged': True, 'frozen_base_unchanged': True}
        save(destination/('arm-'+arm+'.json'), arms[arm])
        del model, base_model, optimizer, params, loss
        gc.collect()
        torch.cuda.empty_cache()
    assert len({a['initial_adapter_sha256'] for a in arms.values()}) == 1
    save(Path('/output/training.json'), {'plan_sha256': file_hash(ROOT/'plan.json'), 'arms': arms,
        'checkpoints': checkpoints, 'encoder_before': encoder_before, 'frozen_base_before': base_before,
        'audio_contracts_sha256': file_hash(Path('/output/audio-contracts.json')), 'cached_inputs': len(contracts),
        'cache_seconds': cache_seconds, 'GPU': torch.cuda.get_device_name(0), 'training_precision': 'bfloat16'})


def convert():
    import torch
    from ctranslate2.converters import TransformersConverter
    from peft import PeftModel
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, WhisperTokenizerFast

    from north55_speech.decoder_adaptation import tensor_hashes

    plan, training = validate(), read(ROOT/'training.json')
    assert training['plan_sha256'] == file_hash(ROOT/'plan.json')
    base = Path('/models/whisper-small-transformers')
    worker.verify_files(base, plan['base_manifest']['files'])
    torch.set_num_threads(4)
    conversions = {}
    for arm in ARMS:
        checkpoint = EXP/'training'/('checkpoint-'+arm)
        worker.verify_files(checkpoint, training['checkpoints'][arm])
        merged_dir, output = EXP/'merged'/arm, EXP/'models'/plan['model_names'][arm]
        if merged_dir.exists() or output.exists():
            raise ValueError('Preserve converted models')
        base_model = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        adapted = PeftModel.from_pretrained(base_model, checkpoint, local_files_only=True).cuda()
        merged = adapted.merge_and_unload()
        assert tensor_hashes(merged.model.encoder) == training['encoder_before']
        merged.save_pretrained(merged_dir, safe_serialization=True)
        WhisperProcessor.from_pretrained(base, local_files_only=True).save_pretrained(merged_dir)
        WhisperTokenizerFast.from_pretrained(base, local_files_only=True).save_pretrained(merged_dir)
        del base_model, adapted, merged
        gc.collect()
        torch.cuda.empty_cache()
        TransformersConverter(str(merged_dir), copy_files=['tokenizer.json', 'preprocessor_config.json']).convert(str(output), quantization='float16')
        manifest = {'model': output.name, 'repo': 'local_cross_family_weak_data_v7',
            'revision': file_hash(checkpoint/'adapter_model.safetensors'), 'actual_updates': 240, 'arm': arm,
            'train_sha256': plan['dataset_sha256'][arm+'.jsonl'], 'training_rows': len(plan['selected_ids'][arm]),
            'base_manifest': plan['base_manifest'], 'quality_evidence': False, 'release_allowed': False,
            'selection_allowed': False, 'license': 'inherited_base_and_existing_noncommercial_research_source_restrictions',
            'files': {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}
        save(output/'manifest.json', manifest)
        conversions[arm] = manifest
        print('Converted', arm, flush=True)
    save(Path('/output/conversion.json'), {'plan_sha256': file_hash(ROOT/'plan.json'), 'models': conversions})


def load_audio(item):
    if item.get('synthetic_v5'):
        path = EXP/'eval-audio'/(item['id']+'.wav')
        assert file_hash(path) == item['audio_sha256']
        x, rate = sf.read(path, dtype='float32')
        assert rate == 16000 and pcm(x) == item['effective_waveform_sha256']
        return x
    return original_audio_loader(item)


def infer(arm, cpu=False):
    from scripts import decoding_diagnostics
    from scripts import publisher_training_v3 as evaluation
    plan = validate()
    evaluation.validate = validate
    decoding_diagnostics.load_audio = load_audio
    original_read = evaluation.read

    def adjusted_read(path):
        value = original_read(path)
        if path == ROOT/'conversion.json':
            return {'plan_sha256': value['plan_sha256'], 'model': value['models'][arm]}
        if path == ROOT/'inputs.json' and arm == 'baseline':
            return [i for i in value if i['cohort'] == 'train_new_fit']
        return value

    evaluation.read = adjusted_read
    # The reused evaluator writes to /output. Each Compose invocation mounts a separate directory.
    assert arm in ARMS or arm == 'baseline'
    assert plan['config']['device'] == 'cuda'
    evaluation.infer('cpu' if cpu else ('baseline' if arm == 'baseline' else 'candidate'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'train', 'convert', 'infer', 'score', 'verify'])
    parser.add_argument('arm', nargs='?', default='expanded')
    parser.add_argument('--cpu', action='store_true')
    args = parser.parse_args()
    if args.stage == 'infer':
        infer(args.arm, args.cpu)
    elif args.stage in ('score', 'verify'):
        from scripts import report_cockpit_data_v7
        getattr(report_cockpit_data_v7, args.stage)()
    else:
        globals()[args.stage]()
