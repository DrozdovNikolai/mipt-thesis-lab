"""Matched CE versus CE+KL adaptation on the existing 675 training pairs."""

import argparse
import gc
import hashlib
import os
import time
from collections import Counter
from pathlib import Path

from scripts import nus_convergence as worker

# These are arm identifiers, not optimizer step numbers. Both use 1200 updates.
worker.STEPS = (1, 2)


def train():
    import librosa
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, set_seed
    from transformers.modeling_outputs import BaseModelOutput

    from north55_speech.datasets import load_manifest
    from north55_speech.decoder_adaptation import decoder_targets, tensor_hashes, verify_trainable_decoder
    from north55_speech.nus_training import validate_nus_pair_population
    from north55_speech.retention import base_teacher_logits, masked_teacher_kl, validate_retention_plan

    plan = worker.validate()
    phase = validate_retention_plan(plan)
    manifest = Path('/train/subset.jsonl')
    if worker.file_hash(manifest) != plan['subset_sha256']:
        raise ValueError('Training manifest changed')
    samples = load_manifest(manifest)
    if len(samples) != 675 or [s.sample_id for s in samples] != plan['selected_ids'] or any(s.split != 'train' for s in samples):
        raise ValueError('Only the original 675 train pairs are admitted')
    validate_nus_pair_population(samples, [], plan['permission_evidence_sha256'])
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1 or not torch.cuda.is_bf16_supported():
        raise ValueError('Require one BF16 capable CUDA GPU')
    base = Path('/models/whisper-small-transformers')
    worker.verify_files(base, plan['base_manifest']['files'])
    destination = worker.EXP / 'training'
    if destination.exists():
        raise ValueError('Preserve previous training artifacts; never silently restart an arm')
    destination.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    set_seed(55)
    processor = WhisperProcessor.from_pretrained(base, local_files_only=True)
    original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True).cuda().eval()
    encoder_before = tensor_hashes(original.model.encoder)
    frozen_base_before = tensor_hashes(original)
    cached, contracts = [], []
    started = time.perf_counter()
    # Encoder is immutable with dropout disabled; cache only audio-derived states.
    for index, sample in enumerate(samples):
        path = (Path('/audio') / sample.audio_path).resolve()
        if not path.is_relative_to(Path('/audio')) or worker.file_hash(path) != sample.audio_sha256:
            raise ValueError('Training waveform changed')
        waveform, _ = librosa.load(path, sr=16000, mono=False)
        if waveform.ndim == 2:
            waveform = waveform[sample.channel]
        elif sample.channel != 0:
            raise ValueError('Invalid mono channel')
        if not 0 < len(waveform) <= 480000:
            raise ValueError('Empty/truncated waveform is forbidden')
        processor.tokenizer.set_prefix_tokens(language=sample.language, task='transcribe')
        tokens = processor.tokenizer(sample.reference_text).input_ids
        if not sample.reference_text or len(tokens) > 448 or tokens[0] != original.config.decoder_start_token_id:
            raise ValueError('Empty/truncated/misaligned target')
        features = processor.feature_extractor(waveform, sampling_rate=16000, return_tensors='pt').input_features.cuda()
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
            states = original.model.encoder(features).last_hidden_state.cpu()
        labels = torch.tensor([tokens[1:]], dtype=torch.long)
        cached.append((states, labels))
        contracts.append({'id': sample.sample_id, 'language': sample.language, 'prefix': tokens[:4],
            'tokens': len(tokens), 'samples': len(waveform),
            'waveform_sha256': hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest(),
            'encoder_state_sha256': hashlib.sha256(states.view(torch.uint8).numpy().tobytes()).hexdigest()})
        if (index + 1) % 100 == 0:
            print('Cached train audio', index + 1, '/675', flush=True)
    cache_seconds = time.perf_counter() - started
    del original, features, states
    gc.collect()
    torch.cuda.empty_cache()
    # The schedule is generated once, independent of labels, outputs and arm.
    generator = torch.Generator().manual_seed(55)
    schedule = []
    while len(schedule) < phase['updates_per_arm'] * phase['accumulation']:
        schedule.extend(torch.randperm(len(samples), generator=generator).tolist())
    schedule = schedule[:phase['updates_per_arm'] * phase['accumulation']]
    schedule_ids = [samples[i].sample_id for i in schedule]
    schedule_hash = hashlib.sha256('\n'.join(schedule_ids).encode()).hexdigest()
    checkpoints, arms = {}, {}
    for arm, weight in phase['arms'].items():
        set_seed(55)
        original = WhisperForConditionalGeneration.from_pretrained(base, local_files_only=True)
        original.config.use_cache = False
        model = get_peft_model(original, LoraConfig(r=8, lora_alpha=16,
            target_modules=decoder_targets(original), lora_dropout=.05, bias='none')).cuda()
        trainable = verify_trainable_decoder(model)
        initial_adapter = {n: p.detach().cpu().clone() for n, p in model.named_parameters() if p.requires_grad}
        initial_hash = hashlib.sha256(b''.join(p.numpy().tobytes() for p in initial_adapter.values())).hexdigest()
        params = [p for p in model.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(params, lr=phase['learning_rate'], weight_decay=0., fused=True)
        optimizer.zero_grad(set_to_none=True)
        seen, logs = Counter(), []
        ce_sum = kl_sum = 0.
        started = time.perf_counter()
        model.train()
        probe_states, probe_labels = cached[0]
        probe = {'encoder_outputs': BaseModelOutput(last_hidden_state=probe_states.cuda()), 'labels': probe_labels.cuda()}
        with torch.autocast('cuda', dtype=torch.bfloat16):
            teacher_before = base_teacher_logits(model, **probe)
        teacher_hash_before = hashlib.sha256(teacher_before.cpu().view(torch.uint8).numpy().tobytes()).hexdigest()
        del teacher_before
        for update in range(1, phase['updates_per_arm'] + 1):
            for index in schedule[(update - 1)*4:update*4]:
                states, labels = cached[index]
                batch = {'encoder_outputs': BaseModelOutput(last_hidden_state=states.cuda()), 'labels': labels.cuda()}
                with torch.autocast('cuda', dtype=torch.bfloat16):
                    teacher = base_teacher_logits(model, **batch) if weight else None
                    output = model(**batch)
                    kl = masked_teacher_kl(output.logits, teacher, batch['labels'], phase['temperature']) if weight else output.loss.new_zeros(())
                    loss = output.loss + weight * kl
                if not torch.isfinite(loss):
                    raise ValueError('Nonfinite loss; preserve failure without skipped updates')
                (loss / 4).backward()
                ce_sum += float(output.loss.detach())
                kl_sum += float(kl.detach())
                seen[samples[index].sample_id] += 1
                del batch, output, teacher, loss, kl
            grad_norm = torch.nn.utils.clip_grad_norm_(params, 1., error_if_nonfinite=True)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            if update % 100 == 0:
                record = {'updates': update, 'ce': ce_sum/400, 'kl': kl_sum/400,
                    'grad_norm': float(grad_norm), 'seconds': time.perf_counter()-started}
                logs.append(record)
                print('arm', arm, worker.json.dumps(record), flush=True)
                ce_sum = kl_sum = 0.
        actual = sorted({int(v['step'].item()) for v in optimizer.state.values()})
        if actual != [1200] or len(optimizer.state) != len(trainable) or set(seen) != set(plan['selected_ids']):
            raise ValueError('Actual optimizer updates/coverage failed')
        verify_trainable_decoder(model)
        encoder_after = tensor_hashes(model.get_base_model().model.encoder)
        if encoder_after != encoder_before:
            raise ValueError('Encoder changed')
        # Strip PEFT wrappers from all frozen base parameters to compare to original.
        frozen_after = {}
        for name, value in model.get_base_model().state_dict().items():
            if '.lora_' not in name:
                frozen_after[name.replace('.base_layer.', '.')] = hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest()
        if frozen_after != frozen_base_before:
            raise ValueError('Frozen teacher/base weights changed')
        with torch.autocast('cuda', dtype=torch.bfloat16):
            teacher_after = base_teacher_logits(model, **probe)
        teacher_hash_after = hashlib.sha256(teacher_after.cpu().view(torch.uint8).numpy().tobytes()).hexdigest()
        if teacher_hash_before != teacher_hash_after:
            raise ValueError('Teacher output changed after adaptation')
        folder = destination / f'checkpoint-{arm}'
        model.save_pretrained(folder, safe_serialization=True)
        torch.save(optimizer.state_dict(), folder / 'optimizer.pt')
        torch.save({'cpu': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state()}, folder / 'rng.pt')
        checkpoints[arm] = {p.name: worker.file_hash(p) for p in folder.iterdir() if p.is_file()}
        arms[arm] = {'kl_weight': weight, 'actual_updates': actual[0], 'optimizer_tensors': len(optimizer.state),
            'training_seconds': time.perf_counter()-started, 'coverage': dict(seen), 'schedule_sha256': schedule_hash,
            'initial_adapter_sha256': initial_hash, 'trainable_tensors': trainable, 'history': logs,
            'encoder_unchanged': True, 'frozen_base_unchanged': True,
            'teacher_before_sha256': teacher_hash_before, 'teacher_after_sha256': teacher_hash_after}
        worker.save_new(destination / f'arm-{arm}.json', arms[arm])
        del model, original, optimizer, params, probe, teacher_after, initial_adapter
        gc.collect()
        torch.cuda.empty_cache()
    if len({v['initial_adapter_sha256'] for v in arms.values()}) != 1:
        raise ValueError('Matched initial adapters differ')
    worker.save_new(Path(os.environ.get('NORTH55_DIAGNOSTIC_OUTPUT', '/study')) / 'training.json', {
        'plan_sha256': worker.file_hash(worker.ROOT / 'plan.json'), 'arms': arms, 'checkpoints': checkpoints,
        'encoder_before': encoder_before, 'frozen_base_before': frozen_base_before,
        'cache_seconds': cache_seconds, 'audio_label_contract': contracts, 'schedule_sha256': schedule_hash,
        'GPU': torch.cuda.get_device_name(0), 'training_precision': 'bfloat16', 'test_accessed': False,
        'dev_accessed': False, 'quality_evidence': False})


def score():
    from north55_speech.metrics import corpus_counts, paired_cluster_bootstrap
    from north55_speech.retention import validate_retention_plan
    from scripts.research_audio_evidence import write_legacy_evidence

    plan = worker.validate()
    validate_retention_plan(plan)
    inputs = worker.read(worker.ROOT / 'inputs.json')
    counts, failures = {}, {}
    for arm in worker.STEPS:
        failures[str(arm)] = {}
        for stage in ('fit', 'transfer'):
            parent, candidate, failed = worker.scored(stage, arm)
            failures[str(arm)][stage] = failed
            for item in inputs[stage]:
                counts.setdefault(item['id'], {})['parent'] = parent[item['id']]
                counts[item['id']][str(arm)] = candidate[item['id']]
    groups = {'nus_training_fit': inputs['fit']}
    groups.update({c: [i for i in inputs['transfer'] if i['cohort'] == c] for c in {i['cohort'] for i in inputs['transfer']}})
    cohorts = {}
    for cohort, items in sorted(groups.items()):
        entry = {'samples': len(items), 'groups': len({i['group_id'] for i in items}),
            'scores': {arm: corpus_counts([counts[i['id']][arm] for i in items]) for arm in ('parent', '1', '2')}}
        comparisons = {}
        for baseline, candidate in [('parent', '1'), ('parent', '2'), ('1', '2')]:
            a, b = (entry['scores'][arm]['wer_lexical_corpus'] for arm in (baseline, candidate))
            comp = {'wer_delta': b-a if a is not None and b is not None else None,
                'relative_reduction': (a-b)/a if a else None, 'independent_confirmation': False}
            if cohort not in ('nus_training_fit', 'noise_only', 'bleriot_b_noise'):
                comp['bootstrap'] = paired_cluster_bootstrap([{'group_id': i['group_id'],
                    'baseline': counts[i['id']][baseline], 'candidate': counts[i['id']][candidate]} for i in items],
                    resamples=2000, seed=55, confidence=.95)
            comparisons[candidate + '_vs_' + baseline] = comp
        entry['comparisons'] = comparisons
        if cohort in ('noise_only', 'bleriot_b_noise'):
            minutes = sum(i['duration_sec'] for i in items)/60
            entry.update(minutes=minutes, inserted_words_per_minute={a: v['I']/minutes for a, v in entry['scores'].items()})
        cohorts[cohort] = entry
    checks = {}
    for arm in ('1', '2'):
        human = cohorts['partial_human_dev']['comparisons'][arm + '_vs_parent']
        checks[arm] = {'human_point': human['relative_reduction'] >= .10, 'human_CI': human['bootstrap']['upper'] < 0,
            'clean_EN': cohorts['general_clean']['comparisons'][arm + '_vs_parent']['wer_delta'] <= .01,
            'general_RU': cohorts['general_ru']['comparisons'][arm + '_vs_parent']['wer_delta'] <= .01,
            'noise': all(cohorts[c]['inserted_words_per_minute'][arm] <= cohorts[c]['inserted_words_per_minute']['parent']
                         for c in ('noise_only', 'bleriot_b_noise')), 'runtime': not any(failures[arm].values())}
    result = {'plan_sha256': worker.file_hash(worker.ROOT / 'plan.json'), 'cohorts': cohorts,
        'checks': checks, 'runtime_failures': failures, 'fixed_candidate': 2,
        'release': 'FAIL' if not all(checks['2'].values()) else 'NEEDS_MORE_DATA',
        'independent_quality': 'NEEDS_MORE_DATA', 'critical_entities': 'NEEDS_MORE_DATA',
        'NLP': 'NEEDS_MORE_DATA', 'quality_evidence': False, 'selection_allowed': False,
        'test_accessed': False, 'release_promoted': False}
    worker.save_new(worker.ROOT / 'comparison.json', result)
    worker.save_new(worker.ROOT / 'scored-counts.json', counts)
    write_legacy_evidence(worker.ROOT / 'legacy-waveform-evidence.json')
    print(worker.json.dumps({'WER': {c: {a: v['wer_lexical_corpus'] for a, v in r['scores'].items()} for c, r in cohorts.items()},
        'checks': checks, 'release': result['release']}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['train', 'convert', 'fit', 'transfer', 'cpu', 'score-transfer'])
    parser.add_argument('arm', nargs='?', type=int, choices=[1, 2])
    args = parser.parse_args()
    if args.stage in ('fit', 'transfer', 'cpu'):
        if args.arm is None:
            parser.error('arm is required')
        worker.infer('fit' if args.stage == 'cpu' else args.stage, args.arm, cpu=args.stage == 'cpu')
    else:
        {'train': train, 'convert': worker.convert, 'score-transfer': score}[args.stage]()
